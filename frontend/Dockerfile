# syntax=docker/dockerfile:1

# Stage 1: Build the Vite React frontend
FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies using clean install
COPY package.json package-lock.json ./
RUN npm ci

# Copy source code and config
COPY . .

# Build argument to allow baking an explicit external API URL if not using reverse proxy
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

# Build production bundle to /app/dist
RUN npm run build

# Stage 2: Serve production bundle with Nginx
FROM nginx:alpine-slim

# Template environment variables for runtime Nginx reverse proxy configuration
ENV PORT=80 \
    BACKEND_URL=http://backend:8000 \
    NGINX_ENVSUBST_FILTER="^(PORT|BACKEND_URL)$"

# Copy custom Nginx configuration template for runtime envsubst substitution
COPY nginx.conf /etc/nginx/templates/default.conf.template

# Copy compiled static assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
    CMD wget -qO- http://127.0.0.1:${PORT}/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
