"""Phase 4 tests: rule management, content submission, deterministic compliance engine,
correction/re-analysis, tenant isolation and RBAC."""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import create_access_token
from app.main import app
from app.models import OrganisationMembership, RoleName, User
from app.services import compliance_engine as eng
from app.services.organisation_service import get_role_by_name
from tests.test_stage3_2_brand_kit_service_and_api import (  # noqa: F401  (fixtures)
    _create_test_user_and_org,
    anyio_backend,
    test_db,
)


# ------------------------------------------------------------------ engine unit tests
def _rule(code, rtype, pattern, severity="HIGH", mode="CASE_INSENSITIVE", **kw):
    return eng.RuleSpec(
        id=str(uuid.uuid4()),
        rule_code=code,
        rule_type=rtype,
        severity=severity,
        title=f"Rule {code}",
        description="Brand policy.",
        target_pattern=pattern,
        match_mode=mode,
        **kw,
    )


def test_engine_banned_phrase_positions_and_evidence_are_exact():
    text = "We offer Guaranteed Returns today. Truly guaranteed returns for all."
    rule = _rule("BAN-1", "PROHIBITED_TERM", "guaranteed returns", "CRITICAL", suggested_replacement="potential returns")
    result = eng.analyze(text, [rule])
    assert len(result["findings"]) == 2
    for f in result["findings"]:
        assert text[f["start"] : f["end"]] == f["matched_text"]
        assert f["matched_text"].lower() == "guaranteed returns"
        assert f["matched_text"] in f["evidence_excerpt"]
        assert f["rule_code"] == "BAN-1" and f["severity"] == "CRITICAL"
        assert f["explanation"] and "potential returns" in f["recommended_correction"]
    assert [f["start"] for f in result["findings"]] == [9, text.lower().index("guaranteed returns", 20)]


def test_engine_match_modes():
    word = _rule("W", "PROHIBITED_TERM", "art", mode="WORD_BOUNDARY")
    assert eng.analyze("start the art show", [word])["findings"][0]["start"] == 10
    assert len(eng.analyze("start the art show", [word])["findings"]) == 1
    exact = _rule("E", "PROHIBITED_TERM", "Cure", mode="EXACT")
    assert eng.analyze("a cure and a Cure", [exact])["findings"][0]["matched_text"] == "Cure"
    rx = _rule("R", "PROHIBITED_TERM", r"\b\d{2,3}% (?:off|discount)\b", mode="REGEX")
    assert eng.analyze("Get 50% off now", [rx])["findings"][0]["matched_text"] == "50% off"


def test_engine_missing_disclaimer_and_present_disclaimer():
    disc = _rule(
        "DISC-1", "MANDATORY_DISCLAIMER", "risk", "HIGH",
        required_disclaimer_text="Investments are subject to market risk.",
    )
    missing = eng.analyze("Buy our fund today.", [disc])
    f = missing["findings"][0]
    assert f["kind"] == "MISSING_DISCLAIMER"
    assert f["start"] is None and f["matched_text"] is None and f["evidence_excerpt"] is None
    assert "Investments are subject to market risk." in f["recommended_correction"]
    ok = eng.analyze("Buy our fund today.  INVESTMENTS are subject\nto market risk.", [disc])
    assert ok["findings"] == [] and ok["result"] == "PASS"


def test_engine_disclaimer_trigger_pattern():
    disc = _rule(
        "DISC-2", "MANDATORY_DISCLAIMER", "T&C apply", "MEDIUM",
        config={"trigger_pattern": "free trial"},
    )
    assert eng.analyze("Buy now.", [disc])["findings"] == []
    f = eng.analyze("Start your free trial!", [disc])["findings"][0]
    assert f["trigger_text"] == "free trial" and f["trigger_start"] == 11


def test_engine_missing_required_terminology():
    term = _rule("TERM-1", "MANDATORY_TERMINOLOGY", "Inkloom", "LOW", mode="EXACT")
    assert eng.analyze("Our tool is great.", [term])["findings"][0]["kind"] == "MISSING_TERMINOLOGY"
    assert eng.analyze("Inkloom is great.", [term])["findings"] == []


def test_engine_price_integrity_only_with_approved_facts():
    rule = _rule("PRICE-1", "PRICE_INTEGRITY", "price", "HIGH")
    assert eng.analyze("Only $99 today", [rule])["findings"] == []  # nothing to verify against
    res = eng.analyze("Only $99 or $120 today", [rule], approved_prices=["$99"])
    assert [f["matched_text"] for f in res["findings"]] == ["$120"]


def test_engine_score_is_transparent():
    rules = [
        _rule("A", "PROHIBITED_TERM", "alpha", "CRITICAL"),
        _rule("B", "PROHIBITED_TERM", "beta", "MEDIUM"),
        _rule("C", "PROHIBITED_TERM", "gamma", "LOW"),
        _rule("D", "PROHIBITED_TERM", "delta", "INFO"),
    ]
    r = eng.analyze("alpha beta gamma delta", rules)
    assert r["score"] == 100 - 40 - 10 - 5 and r["result"] == "FAIL"  # critical => FAIL
    assert r["scoring"]["total_penalty"] == 55
    r2 = eng.analyze("beta gamma delta", rules)
    assert r2["score"] == 85 and r2["result"] == "PASS"
    assert eng.analyze("clean", rules)["score"] == 100


def test_engine_apply_corrections_and_compare():
    text = "Guaranteed returns await. Sign up."
    rules = [
        _rule("BAN-1", "PROHIBITED_TERM", "guaranteed returns", "CRITICAL", suggested_replacement="Potential returns"),
        _rule("DISC-1", "MANDATORY_DISCLAIMER", "x", "HIGH", required_disclaimer_text="Capital at risk."),
    ]
    before = eng.analyze(text, rules)
    fixed = eng.apply_corrections(text, before["findings"])
    assert fixed["corrected_text"].startswith("Potential returns await.")
    assert fixed["corrected_text"].endswith("Capital at risk.")
    after = eng.analyze(fixed["corrected_text"], rules)
    assert after["result"] == "PASS" and after["findings"] == []
    cmp = eng.compare_analyses(text, before, fixed["corrected_text"], after)
    assert len(cmp["resolved_findings"]) == 2 and cmp["score_delta"] > 0 and cmp["text_diff"]


def test_engine_rejects_unsafe_regex():
    with pytest.raises(eng.RuleDefinitionError):
        eng.validate_pattern(r"(a+)+$", "REGEX")
    with pytest.raises(eng.RuleDefinitionError):
        eng.validate_pattern("(unclosed", "REGEX")


# ------------------------------------------------------------------ API helpers
BASE = "/api/v1/organisations"


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


async def _setup_published_kit(client, org_id, headers, with_rules=True):
    r = await client.post(f"{BASE}/{org_id}/brand-kits", headers=headers, json={"name": "Acme Finance"})
    assert r.status_code == 201, r.text
    kit_id, ver_id = r.json()["id"], r.json()["versions"][0]["id"]
    rules_url = f"{BASE}/{org_id}/brand-kits/{kit_id}/versions/{ver_id}/rules"
    rule_ids = {}
    if with_rules:
        specs = {
            "ban": {
                "rule_type": "PROHIBITED_TERM", "title": "No guaranteed returns",
                "description": "Returns can never be guaranteed.", "target_pattern": "guaranteed returns",
                "severity": "CRITICAL", "suggested_replacement": "potential returns", "rule_code": "BAN-GR",
            },
            "disc": {
                "rule_type": "MANDATORY_DISCLAIMER", "title": "Risk disclaimer",
                "description": "All investment copy needs the risk statement.", "target_pattern": "market risk",
                "required_disclaimer_text": "Investments are subject to market risk.", "severity": "HIGH",
            },
            "term": {
                "rule_type": "MANDATORY_TERMINOLOGY", "title": "Use brand name",
                "description": "Mention Acme.", "target_pattern": "Acme", "match_mode": "EXACT", "severity": "LOW",
            },
        }
        for key, body in specs.items():
            c = await client.post(rules_url, headers=headers, json=body)
            assert c.status_code == 201, c.text
            assert c.json()["approval_status"] == "PENDING_REVIEW"
            rule_ids[key] = c.json()["id"]
            a = await client.post(f"{rules_url}/{rule_ids[key]}/approve", headers=headers)
            assert a.status_code == 200 and a.json()["approval_status"] == "APPROVED", a.text
    p = await client.post(f"{BASE}/{org_id}/brand-kits/{kit_id}/versions/{ver_id}/publish", headers=headers)
    assert p.status_code == 200, p.text
    return kit_id, ver_id, rule_ids, rules_url


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


def _add_member(db, org, email, role):
    u = User(
        id=uuid.uuid4(), full_name=f"U {role}", email=email, password_hash="x", is_active=True, is_verified=True
    )
    db.add(u)
    db.flush()
    db.add(
        OrganisationMembership(
            id=uuid.uuid4(), user_id=u.id, organisation_id=org.id,
            role_id=get_role_by_name(db, role).id, status="ACTIVE",
        )
    )
    db.commit()
    return create_access_token(subject=u.id, email=u.email)[0]


# ------------------------------------------------------------------ API tests
@pytest.mark.anyio
async def test_end_to_end_submit_findings_correct_and_reanalyse(test_db):
    _, org, token = _create_test_user_and_org(test_db, "e2e", RoleName.ADMIN)
    h = _hdr(token)
    async with _client() as c:
        kit_id, ver_id, _, _ = await _setup_published_kit(c, org.id, h)
        text = "Acme funds offer guaranteed returns to everyone."
        r = await c.post(f"{BASE}/{org.id}/compliance/submissions", headers=h,
                         json={"brand_kit_id": kit_id, "title": "Landing page", "content_text": text})
        assert r.status_code == 201, r.text
        sub = r.json()
        assert sub["brand_kit_version_id"] == ver_id and sub["organisation_id"] == str(org.id)
        an = sub["analysis"]
        assert an["result"] == "FAIL" and an["rules_evaluated"] == 3
        by_code = {f["rule_code"]: f for f in an["findings"]}
        ban = by_code["BAN-GR"]
        assert text[ban["start"] : ban["end"]] == ban["matched_text"] == "guaranteed returns"
        assert ban["severity"] == "CRITICAL" and ban["evidence_excerpt"] and ban["explanation"]
        assert "potential returns" in ban["recommended_correction"]
        assert any(f["kind"] == "MISSING_DISCLAIMER" for f in an["findings"])
        assert an["score"] == 100 - 40 - 20  # critical + high; brand name present

        # Persisted & retrievable
        g = await c.get(f"{BASE}/{org.id}/compliance/submissions/{sub['id']}", headers=h)
        assert g.status_code == 200 and g.json()["analysis"]["findings"] == an["findings"]

        # Apply suggested corrections -> new revision that passes, with comparison
        fx = await c.post(f"{BASE}/{org.id}/compliance/submissions/{sub['id']}/apply-corrections", headers=h)
        assert fx.status_code == 201, fx.text
        rev = fx.json()
        assert rev["parent_submission_id"] == sub["id"] and rev["revision_number"] == 2
        assert "potential returns" in rev["content_text"]
        assert rev["content_text"].endswith("Investments are subject to market risk.")
        assert rev["analysis"]["result"] == "PASS" and rev["analysis"]["findings"] == []
        cmp = rev["comparison"]
        assert cmp["score_before"] == 40 and cmp["score_after"] == 100
        assert len(cmp["resolved_findings"]) == 2 and cmp["new_findings"] == [] and cmp["text_diff"]
        # original is untouched
        orig = await c.get(f"{BASE}/{org.id}/compliance/submissions/{sub['id']}", headers=h)
        assert orig.json()["content_text"] == text

        # Manual edit that re-introduces a violation is re-analysed
        ed = await c.post(f"{BASE}/{org.id}/compliance/submissions/{rev['id']}/revisions", headers=h,
                          json={"content_text": rev["content_text"] + " Also guaranteed returns!"})
        assert ed.status_code == 201 and ed.json()["analysis"]["result"] == "FAIL"
        assert len(ed.json()["comparison"]["new_findings"]) == 1

        lst = await c.get(f"{BASE}/{org.id}/compliance/submissions?brand_kit_id={kit_id}", headers=h)
        assert lst.status_code == 200 and len(lst.json()) == 3


@pytest.mark.anyio
async def test_unapproved_rules_ignored_and_submit_requires_published_version(test_db):
    _, org, token = _create_test_user_and_org(test_db, "gate", RoleName.ADMIN)
    h = _hdr(token)
    async with _client() as c:
        k = await c.post(f"{BASE}/{org.id}/brand-kits", headers=h, json={"name": "Gate Kit"})
        kit_id, ver_id = k.json()["id"], k.json()["versions"][0]["id"]
        # No published version yet
        r = await c.post(f"{BASE}/{org.id}/compliance/submissions", headers=h,
                         json={"brand_kit_id": kit_id, "content_text": "hello"})
        assert r.status_code == 409
        rules_url = f"{BASE}/{org.id}/brand-kits/{kit_id}/versions/{ver_id}/rules"
        a = await c.post(rules_url, headers=h, json={
            "rule_type": "PROHIBITED_TERM", "title": "Pending", "description": "dd", "target_pattern": "bad"})
        assert a.status_code == 201
        # Publishing is blocked while a rule is unreviewed? (pre-publish gate) -> approve then reject path
        rej = await c.post(f"{rules_url}/{a.json()['id']}/reject", headers=h, json={"notes": "nope"})
        assert rej.json()["approval_status"] == "REJECTED"
        # Rejected rules block publish per existing gate; delete it, then publish with zero rules.
        d = await c.delete(f"{rules_url}/{a.json()['id']}", headers=h)
        assert d.status_code == 204
        assert (await c.post(f"{BASE}/{org.id}/brand-kits/{kit_id}/versions/{ver_id}/publish", headers=h)).status_code == 200
        r = await c.post(f"{BASE}/{org.id}/compliance/submissions", headers=h,
                         json={"brand_kit_id": kit_id, "content_text": "this is bad"})
        assert r.status_code == 201 and r.json()["analysis"]["findings"] == []
        assert r.json()["analysis"]["rules_evaluated"] == 0


@pytest.mark.anyio
async def test_rule_edits_blocked_on_published_and_reset_approval_on_change(test_db):
    _, org, token = _create_test_user_and_org(test_db, "edit", RoleName.ADMIN)
    h = _hdr(token)
    async with _client() as c:
        k = await c.post(f"{BASE}/{org.id}/brand-kits", headers=h, json={"name": "Edit Kit"})
        kit_id, ver_id = k.json()["id"], k.json()["versions"][0]["id"]
        url = f"{BASE}/{org.id}/brand-kits/{kit_id}/versions/{ver_id}/rules"
        rid = (await c.post(url, headers=h, json={
            "rule_type": "PROHIBITED_TERM", "title": "Tt", "description": "dd", "target_pattern": "free"})).json()["id"]
        await c.post(f"{url}/{rid}/approve", headers=h)
        p = await c.patch(f"{url}/{rid}", headers=h, json={"severity": "low", "target_pattern": "gratis"})
        assert p.status_code == 200
        assert p.json()["severity"] == "LOW" and p.json()["approval_status"] == "PENDING_REVIEW"
        # metadata-only changes keep approval
        await c.post(f"{url}/{rid}/approve", headers=h)
        p2 = await c.patch(f"{url}/{rid}", headers=h, json={"title": "Renamed"})
        assert p2.json()["approval_status"] == "APPROVED"
        # filters
        assert len((await c.get(f"{url}?rule_type=PROHIBITED_TERM", headers=h)).json()) == 1
        assert len((await c.get(f"{url}?rule_type=MANDATORY_DISCLAIMER", headers=h)).json()) == 0
        # invalid inputs
        assert (await c.post(url, headers=h, json={"rule_type": "NOPE", "title": "Tt", "description": "dd",
                                                    "target_pattern": "x"})).status_code == 422
        assert (await c.post(url, headers=h, json={"rule_type": "PROHIBITED_TERM", "title": "Tt", "description": "dd",
                                                    "target_pattern": "(a+)+$", "match_mode": "REGEX"})).status_code == 422
        dup = {"rule_type": "PROHIBITED_TERM", "title": "Tt", "description": "dd", "target_pattern": "x", "rule_code": "DUP-1"}
        assert (await c.post(url, headers=h, json=dup)).status_code == 201
        assert (await c.post(url, headers=h, json=dup)).status_code == 409
        # publish, then edits are rejected
        pub = await c.post(f"{BASE}/{org.id}/brand-kits/{kit_id}/versions/{ver_id}/publish", headers=h)
        assert pub.status_code == 422  # DUP-1 still pending: existing publish gate
        await c.post(f"{url}/{(await c.get(f'{url}?approval_status=PENDING_REVIEW', headers=h)).json()[0]['id']}/approve", headers=h)
        assert (await c.post(f"{BASE}/{org.id}/brand-kits/{kit_id}/versions/{ver_id}/publish", headers=h)).status_code == 200
        assert (await c.patch(f"{url}/{rid}", headers=h, json={"title": "XX"})).status_code == 409
        assert (await c.delete(f"{url}/{rid}", headers=h)).status_code == 409
        assert (await c.post(url, headers=h, json={"rule_type": "PROHIBITED_TERM", "title": "Tt", "description": "dd",
                                                    "target_pattern": "y"})).status_code == 409


@pytest.mark.anyio
async def test_tenant_isolation_for_rules_and_submissions(test_db):
    _, org_a, tok_a = _create_test_user_and_org(test_db, "iso_a", RoleName.ADMIN)
    _, org_b, tok_b = _create_test_user_and_org(test_db, "iso_b", RoleName.ADMIN)
    ha, hb = _hdr(tok_a), _hdr(tok_b)
    async with _client() as c:
        kit_id, ver_id, rule_ids, rules_url = await _setup_published_kit(c, org_a.id, ha)
        sub = (await c.post(f"{BASE}/{org_a.id}/compliance/submissions", headers=ha,
                            json={"brand_kit_id": kit_id, "content_text": "guaranteed returns"})).json()

        # B cannot use A's URL space at all
        assert (await c.get(f"{BASE}/{org_a.id}/compliance/submissions/{sub['id']}", headers=hb)).status_code == 403
        assert (await c.get(rules_url.replace(str(org_a.id), str(org_b.id)), headers=hb)).status_code == 404
        # B cannot read A's submission via B's own org path
        assert (await c.get(f"{BASE}/{org_b.id}/compliance/submissions/{sub['id']}", headers=hb)).status_code == 404
        # B cannot submit against A's brand kit
        r = await c.post(f"{BASE}/{org_b.id}/compliance/submissions", headers=hb,
                         json={"brand_kit_id": kit_id, "content_text": "x"})
        assert r.status_code == 404
        # B cannot revise / correct A's submission
        assert (await c.post(f"{BASE}/{org_b.id}/compliance/submissions/{sub['id']}/revisions", headers=hb,
                             json={"content_text": "x"})).status_code == 404
        assert (await c.post(f"{BASE}/{org_b.id}/compliance/submissions/{sub['id']}/apply-corrections",
                             headers=hb)).status_code == 404
        # B's list is empty; cannot touch A's rule through own org path
        assert (await c.get(f"{BASE}/{org_b.id}/compliance/submissions", headers=hb)).json() == []
        own = await c.post(f"{BASE}/{org_b.id}/brand-kits", headers=hb, json={"name": "B Kit"})
        bk, bv = own.json()["id"], own.json()["versions"][0]["id"]
        assert (await c.get(f"{BASE}/{org_b.id}/brand-kits/{bk}/versions/{bv}/rules/{rule_ids['ban']}",
                            headers=hb)).status_code == 404
        # Unauthenticated
        assert (await c.get(f"{BASE}/{org_a.id}/compliance/submissions")).status_code == 401


@pytest.mark.anyio
async def test_rbac_permissions_for_rules_and_submissions(test_db):
    _, org, tok_admin = _create_test_user_and_org(test_db, "rbac4", RoleName.ADMIN)
    tok_bm = _add_member(test_db, org, "bm4@example.com", RoleName.BRAND_MANAGER)
    tok_cc = _add_member(test_db, org, "cc4@example.com", RoleName.CONTENT_CREATOR)
    tok_rv = _add_member(test_db, org, "rv4@example.com", RoleName.REVIEWER)
    async with _client() as c:
        kit_id, ver_id, rule_ids, rules_url = await _setup_published_kit(c, org.id, _hdr(tok_admin))
        body = {"brand_kit_id": kit_id, "content_text": "Acme text"}
        sub_url = f"{BASE}/{org.id}/compliance/submissions"

        # Rule management: BRAND_MANAGE only
        rule_body = {"rule_type": "PROHIBITED_TERM", "title": "Tt", "description": "dd", "target_pattern": "z"}
        # (version is published so a permitted user gets 409; unpermitted must be 403 first)
        assert (await c.post(rules_url, headers=_hdr(tok_cc), json=rule_body)).status_code == 403
        assert (await c.post(rules_url, headers=_hdr(tok_rv), json=rule_body)).status_code == 403
        assert (await c.post(rules_url, headers=_hdr(tok_bm), json=rule_body)).status_code == 409
        assert (await c.post(f"{rules_url}/{rule_ids['ban']}/approve", headers=_hdr(tok_cc))).status_code == 403
        assert (await c.patch(f"{rules_url}/{rule_ids['ban']}", headers=_hdr(tok_rv), json={"title": "xx"})).status_code == 403
        assert (await c.delete(f"{rules_url}/{rule_ids['ban']}", headers=_hdr(tok_cc))).status_code == 403
        for t in (tok_admin, tok_bm, tok_cc, tok_rv):
            assert (await c.get(rules_url, headers=_hdr(t))).status_code == 200

        # Submission: CONTENT_CREATE (admin, creator); reviewers & brand managers may only read
        assert (await c.post(sub_url, headers=_hdr(tok_rv), json=body)).status_code == 403
        assert (await c.post(sub_url, headers=_hdr(tok_bm), json=body)).status_code == 403
        made = await c.post(sub_url, headers=_hdr(tok_cc), json=body)
        assert made.status_code == 201
        sid = made.json()["id"]
        assert (await c.post(f"{sub_url}/{sid}/revisions", headers=_hdr(tok_rv), json={"content_text": "x"})).status_code == 403
        assert (await c.post(f"{sub_url}/{sid}/apply-corrections", headers=_hdr(tok_rv))).status_code == 403
        for t in (tok_admin, tok_bm, tok_cc, tok_rv):
            assert (await c.get(f"{sub_url}/{sid}", headers=_hdr(t))).status_code == 200


@pytest.mark.anyio
async def test_input_validation_and_no_correction_available(test_db):
    _, org, token = _create_test_user_and_org(test_db, "val", RoleName.ADMIN)
    h = _hdr(token)
    async with _client() as c:
        kit_id, *_ = await _setup_published_kit(c, org.id, h)
        url = f"{BASE}/{org.id}/compliance/submissions"
        assert (await c.post(url, headers=h, json={"brand_kit_id": kit_id, "content_text": "   "})).status_code == 422
        assert (await c.post(url, headers=h, json={"brand_kit_id": kit_id,
                                                   "content_text": "x" * 50001})).status_code == 422
        clean = await c.post(url, headers=h, json={
            "brand_kit_id": kit_id,
            "content_text": "Acme: potential returns. Investments are subject to market risk."})
        assert clean.json()["analysis"]["result"] == "PASS" and clean.json()["analysis"]["score"] == 100
        # Nothing to correct on a clean submission
        assert (await c.post(f"{url}/{clean.json()['id']}/apply-corrections", headers=h)).status_code == 422
        assert (await c.post(f"{url}/{clean.json()['id']}/apply-corrections", headers=h,
                             json={"finding_ids": ["not-a-finding"]})).status_code == 422
