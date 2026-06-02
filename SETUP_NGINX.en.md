**[日本語](SETUP_NGINX.md)** | **English**

# NGINX Setup Guide

This document describes how to configure NGINX as a reverse proxy to expose the DigitalMATSUMOTO Docker containers externally.
It also covers enabling HTTPS via Let's Encrypt.

---

## Prerequisites

- An Ubuntu / Debian-based host machine
- Docker containers already running (binding ports 8501 / 8899)
- A custom domain or an Azure DNS name configured

## 1. Installing NGINX

```bash
sudo apt update
sudo apt install -y nginx
```

## 2. Creating the configuration file

Create `/etc/nginx/sites-available/digitalmatsumoto`.

```nginx
# HTTP -> HTTPS redirect
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;
}

# HTTPS
server {
    listen 443 ssl;
    server_name your-domain.com;

    # SSL certificate (enable after obtaining it in Step 4)
    ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # SSL settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Timeout settings (LLM execution can take a while, so set generous values)
    proxy_connect_timeout 300s;
    proxy_send_timeout    300s;
    proxy_read_timeout    300s;

    # --- Streamlit WebUI ---
    location / {
        proxy_pass http://127.0.0.1:8501/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support (required by Streamlit)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # --- FastAPI ---
    location /api/ {
        proxy_pass http://127.0.0.1:8899/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # --- JupyterLab (only if needed) ---
    # location /jupyter/ {
    #     proxy_pass http://127.0.0.1:8891/;
    #     proxy_set_header Host $host;
    #     proxy_http_version 1.1;
    #     proxy_set_header Upgrade $http_upgrade;
    #     proxy_set_header Connection "upgrade";
    # }
}
```

> Replace `your-domain.com` with your actual domain name.
> For Azure VMs, this will be a DNS name such as `xxx.japaneast.cloudapp.azure.com`.

## 3. Enabling and verifying the configuration

```bash
# Enable via a symbolic link
sudo ln -sf /etc/nginx/sites-available/digitalmatsumoto /etc/nginx/sites-enabled/

# Disable the default configuration (to prevent conflicts)
sudo rm -f /etc/nginx/sites-enabled/default

# Check the configuration syntax
sudo nginx -t

# Restart NGINX
sudo systemctl restart nginx
```

## 4. Obtaining an SSL certificate (Let's Encrypt)

### 4-1. Installing Certbot

```bash
sudo apt install -y certbot python3-certbot-nginx
```

### 4-2. Obtaining the certificate

```bash
sudo certbot --nginx -d your-domain.com
```

You will be prompted interactively to enter an email address and agree to the terms of service. Once finished, the certificate is automatically placed under `/etc/letsencrypt/live/your-domain.com/`.

> Alternatively, for the first run you can comment out the SSL configuration lines and run certbot over HTTP only, then uncomment them and restart NGINX after the certificate is obtained.

### 4-3. Verifying auto-renewal

Let's Encrypt certificates expire after 90 days, but certbot sets up an auto-renewal timer.

```bash
# Check the timer
sudo systemctl status certbot.timer

# Test renewal manually
sudo certbot renew --dry-run
```

## 5. Firewall configuration

### For Ubuntu (ufw)

```bash
sudo ufw allow 'Nginx Full'  # 80 + 443
sudo ufw reload
```

### For Azure VM

In the Azure Portal, go to "Network Security Group" and add the following inbound rules:

| Priority | Port | Protocol | Action |
|----------|------|----------|--------|
| 100 | 80 | TCP | Allow |
| 110 | 443 | TCP | Allow |

> The Docker container ports (8501, 8891, 8899) do not need to be opened directly to the outside. Access goes through NGINX.

## 6. Verifying the setup

```bash
# Access the WebUI over HTTPS
curl -s -o /dev/null -w "%{http_code}" https://your-domain.com/

# API health check
curl -s https://your-domain.com/api/health

# API message send test
curl -s -X POST https://your-domain.com/api/run \
  -H "Content-Type: application/json" \
  -d '{
    "service_info": {"SERVICE_ID": "API_TEST", "SERVICE_DATA": {}},
    "user_info": {"USER_ID": "TestUser", "USER_DATA": {}},
    "session_id": "NGINX_TEST_001",
    "user_input": "Hello",
    "agent_file": "agent_10Sample.json"
  }' | python3 -m json.tool
```

## Endpoint mapping

| External URL | Proxy target | Purpose |
|--------------|--------------|---------|
| `https://your-domain.com/` | `127.0.0.1:8501` | Streamlit WebUI |
| `https://your-domain.com/api/` | `127.0.0.1:8899` | FastAPI |
| `https://your-domain.com/jupyter/` | `127.0.0.1:8891` | JupyterLab (optional) |

## Troubleshooting

### The WebUI shows a blank screen

Streamlit uses WebSockets, so NGINX must be configured with `Upgrade` headers. Make sure the `location /` block contains the following:

```nginx
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
```

### The API times out

LLM execution takes 10 to 30 seconds. The NGINX default timeout (60 seconds) may not be enough.

```nginx
proxy_read_timeout 300s;
```

### 502 Bad Gateway

The Docker container is not running or the port is not bound correctly.

```bash
# Check container status
docker ps

# Check that the ports are being listened on
ss -tlnp | grep -E '8501|8899'
```
