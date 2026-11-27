FROM public.ecr.aws/docker/library/node:22-bullseye-slim AS build

WORKDIR /app

COPY package*.json ./
COPY vendor/ ./vendor/

RUN npm ci

COPY . .

RUN npm run build:prod

# Production stage with nginx
FROM public.ecr.aws/docker/library/nginx:alpine

# Copy the built Angular app from the build stage
COPY --from=build /app/dist/ng-digibro-frontend/browser /usr/share/nginx/html

# Copy custom nginx configuration if needed (optional)
# COPY nginx.conf /etc/nginx/nginx.conf

# Create a simple nginx config for Angular SPA
RUN echo 'server { \
    listen 80; \
    server_name localhost; \
    root /usr/share/nginx/html; \
    index index.html; \
    location / { \
        try_files $uri $uri/ /index.html; \
    } \
    # Security headers \
    add_header X-Frame-Options "SAMEORIGIN" always; \
    add_header X-Content-Type-Options "nosniff" always; \
    add_header X-XSS-Protection "1; mode=block" always; \
    add_header Referrer-Policy "strict-origin-when-cross-origin" always; \
}' > /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
