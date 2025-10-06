# Deployment Guide - Telegram Bot Moderation System

## 🚀 Production Deployment Guide

### Prerequisites

#### System Requirements
- **Python**: 3.8+ (recommended: 3.11+)
- **Operating System**: Linux (Ubuntu 20.04+), macOS, or Windows 10+
- **Memory**: Minimum 512MB RAM, recommended 1GB+
- **Storage**: Minimum 1GB free space
- **Network**: Stable internet connection for Telegram and OpenAI APIs

#### Required API Keys
- **Telegram Bot Token**: Create bots via [@BotFather](https://t.me/botfather)
  - Main bot token for user interactions
  - Admin bot token for moderation interface
- **OpenAI API Key**: Get from [OpenAI Platform](https://platform.openai.com/)
  - Required for AI responses and corrections
- **Admin Chat ID**: Telegram chat/user ID for admin notifications

### Installation

#### 1. Clone and Setup
```bash
# Clone the repository
git clone <repository-url>
cd "Бот куратор"

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

#### 2. Environment Configuration
```bash
# Create .env file
cp .env.example .env

# Edit .env with your configuration
nano .env
```

**Required Environment Variables:**
```bash
# Main Bot Configuration
BOT_TOKEN=your_main_bot_token_here
OPENAI_API_KEY=sk-your_openai_api_key_here

# Admin Bot Configuration
ADMIN_BOT_TOKEN=your_admin_bot_token_here
ADMIN_CHAT_ID=your_admin_chat_id_here
CORRECTION_ASSISTANT_ID=asst_your_assistant_id_here

# Optional Configuration
METRICS_DATABASE=metrics.db
METRICS_LOG_FILE=metrics.jsonl
ENABLE_METRICS=true
```

#### 3. Database Setup
```bash
# The system will automatically create SQLite databases on first run
# No manual database setup required

# Optional: Verify configuration
python3 -c "from config import Config; print('✅ Configuration loaded successfully')"
```

### Running the System

#### Development Mode
```bash
# Run with full logging
python3 main.py

# The system will start both bots and show startup logs
```

#### Production Mode

##### Using systemd (Linux)
```bash
# Create systemd service file
sudo nano /etc/systemd/system/telegram-bot.service
```

```ini
[Unit]
Description=Telegram Bot Moderation System
After=network.target

[Service]
Type=simple
User=your_username
Group=your_group
WorkingDirectory=/path/to/bot/directory
Environment=PATH=/path/to/bot/directory/venv/bin
ExecStart=/path/to/bot/directory/venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable telegram-bot.service
sudo systemctl start telegram-bot.service

# Check status
sudo systemctl status telegram-bot.service

# View logs
sudo journalctl -u telegram-bot.service -f
```

##### Using PM2 (Cross-platform)
```bash
# Install PM2
npm install -g pm2

# Create ecosystem file
nano ecosystem.config.js
```

```javascript
module.exports = {
  apps: [{
    name: 'telegram-bot',
    script: 'main.py',
    interpreter: 'python3',
    cwd: '/path/to/bot/directory',
    env: {
      NODE_ENV: 'production'
    },
    watch: false,
    max_memory_restart: '1G',
    restart_delay: 5000,
    max_restarts: 10
  }]
};
```

```bash
# Start with PM2
pm2 start ecosystem.config.js

# Setup auto-start
pm2 startup
pm2 save

# Monitor
pm2 status
pm2 logs telegram-bot
```

##### Using Docker
```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create non-root user
RUN useradd -m botuser && chown -R botuser:botuser /app
USER botuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python3 -c "import requests; requests.get('http://localhost:8080/health')" || exit 1

# Run application
CMD ["python3", "main.py"]
```

```bash
# Build and run
docker build -t telegram-bot .
docker run -d --name telegram-bot --env-file .env telegram-bot

# With docker-compose
nano docker-compose.yml
```

```yaml
version: '3.8'
services:
  telegram-bot:
    build: .
    environment:
      - BOT_TOKEN=${BOT_TOKEN}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ADMIN_BOT_TOKEN=${ADMIN_BOT_TOKEN}
      - ADMIN_CHAT_ID=${ADMIN_CHAT_ID}
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python3", "-c", "import sys; sys.exit(0)"]
      interval: 30s
      timeout: 10s
      retries: 3
```

```bash
docker-compose up -d
```

### Monitoring and Maintenance

#### Health Checks
```bash
# Check system status
curl http://localhost:8080/health  # If health endpoint is implemented

# Check logs
tail -f bot_system.log
tail -f metrics.jsonl

# Check process status
ps aux | grep python | grep main.py
```

#### Log Management
```bash
# Rotate logs (add to cron)
# 0 2 * * * /usr/bin/find /path/to/logs -name "*.log" -mtime +7 -delete

# Monitor log files
tail -f bot_system.log | grep ERROR
tail -f metrics.jsonl | jq '.'  # If jq is installed
```

#### Database Maintenance
```bash
# Backup databases
cp metrics.db metrics.db.backup.$(date +%Y%m%d)
cp moderation.db moderation.db.backup.$(date +%Y%m%d)

# Cleanup old data (if needed)
python3 -c "
from services.metrics_service import get_metrics_service
from datetime import datetime, timedelta
# Add cleanup logic here
"
```

### Signal Handling

The system supports graceful shutdown via signals:

```bash
# Graceful shutdown
kill -TERM <pid>
# or
pkill -TERM -f main.py

# Immediate shutdown (not recommended)
kill -KILL <pid>

# Reload configuration (if implemented)
kill -HUP <pid>
```

### Security Considerations

#### Environment Security
```bash
# Secure .env file
chmod 600 .env
chown root:root .env  # Or appropriate user

# Secure database files
chmod 640 *.db
chown botuser:botgroup *.db
```

#### Network Security
- Use HTTPS for all external API calls (handled automatically)
- Implement firewall rules if needed
- Consider VPN for admin access
- Regular security updates for dependencies

#### API Key Security
- Never commit API keys to version control
- Use environment variables or secure key management
- Rotate keys regularly
- Monitor API usage for anomalies

### Performance Optimization

#### Memory Optimization
```python
# Monitor memory usage
import psutil
process = psutil.Process()
print(f"Memory usage: {process.memory_info().rss / 1024 / 1024:.2f} MB")
```

#### Database Optimization
```bash
# SQLite optimization
python3 -c "
import sqlite3
conn = sqlite3.connect('metrics.db')
conn.execute('VACUUM;')
conn.execute('ANALYZE;')
conn.close()
"
```

### Troubleshooting

#### Common Issues

**Bot Not Starting**
```bash
# Check configuration
python3 -c "from config import Config; print(Config.BOT_TOKEN[:10])"

# Check API connectivity
python3 -c "
import httpx
response = httpx.get('https://api.telegram.org/bot<TOKEN>/getMe')
print(response.status_code)
"
```

**High Memory Usage**
```bash
# Check for memory leaks
python3 -m memray run main.py  # If memray is installed

# Monitor metrics
tail -f metrics.jsonl | grep memory
```

**Database Issues**
```bash
# Check database integrity
python3 -c "
import sqlite3
conn = sqlite3.connect('metrics.db')
result = conn.execute('PRAGMA integrity_check;').fetchone()
print(result[0])
conn.close()
"
```

#### Debug Mode
```bash
# Run in debug mode
export LOG_LEVEL=DEBUG
python3 main.py

# Enable verbose metrics
export ENABLE_VERBOSE_METRICS=true
python3 main.py
```

### Scaling Considerations

#### Horizontal Scaling
- Use Redis for shared state between instances
- Implement load balancing for webhook mode
- Database clustering for high-volume scenarios

#### Vertical Scaling
- Monitor CPU and memory usage
- Optimize database queries
- Implement caching where appropriate

### Backup Strategy

#### Automated Backups
```bash
#!/bin/bash
# backup.sh
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/backup/telegram-bot"

mkdir -p $BACKUP_DIR

# Backup databases
cp metrics.db $BACKUP_DIR/metrics_$DATE.db
cp moderation.db $BACKUP_DIR/moderation_$DATE.db

# Backup configuration (without secrets)
cp config.py $BACKUP_DIR/config_$DATE.py

# Cleanup old backups (keep 30 days)
find $BACKUP_DIR -name "*.db" -mtime +30 -delete

echo "Backup completed: $DATE"
```

### Monitoring Dashboard

#### Metrics Collection
```python
# Custom metrics endpoint
from services.metrics_service import get_metrics_service

async def metrics_endpoint():
    metrics = get_metrics_service()
    dashboard = metrics.get_dashboard_data(hours=24)
    return dashboard
```

#### Alerting
```bash
# Simple alerting script
#!/bin/bash
# check_bot_health.sh

HEALTH_URL="http://localhost:8080/health"
response=$(curl -s -o /dev/null -w "%{http_code}" $HEALTH_URL)

if [ $response -ne 200 ]; then
    echo "Bot health check failed: $response" | mail -s "Bot Alert" admin@example.com
fi
```

### Production Checklist

- [ ] Environment variables configured
- [ ] API keys tested and working
- [ ] Database permissions set correctly
- [ ] Log rotation configured
- [ ] Monitoring setup
- [ ] Backup strategy implemented
- [ ] Security hardening applied
- [ ] Documentation updated
- [ ] Team access configured
- [ ] Emergency procedures documented

### Support and Maintenance

#### Regular Maintenance Tasks
- Monitor system performance daily
- Review logs for errors weekly
- Update dependencies monthly
- Test backup/restore procedures quarterly
- Security audit annually

#### Emergency Procedures
- System restart: `systemctl restart telegram-bot`
- Emergency shutdown: `systemctl stop telegram-bot`
- Database recovery: Restore from backup
- Configuration rollback: Git revert + restart

---

🚀 **Your Telegram Bot Moderation System is ready for production!**

For additional support, check the troubleshooting section or review the system logs for detailed error information.