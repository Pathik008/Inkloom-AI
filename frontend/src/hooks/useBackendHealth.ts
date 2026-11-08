import { useState, useEffect, useCallback } from 'react';
import { HealthStatus } from '../types';
import { fetchBackendHealth } from '../services/api';

export function useBackendHealth(pollIntervalMs = 15000) {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  const checkHealth = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchBackendHealth();
      setHealth(data);
      setError(null);
      setLastChecked(new Date());
    } catch (err) {
      setHealth(null);
      setError(err instanceof Error ? err.message : 'Unable to connect to backend API');
      setLastChecked(new Date());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void checkHealth();
    const timer = window.setInterval(() => {
      void checkHealth();
    }, pollIntervalMs);
    return () => window.clearInterval(timer);
  }, [checkHealth, pollIntervalMs]);

  return { health, loading, error, lastChecked, refresh: checkHealth };
}
