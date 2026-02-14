#!/bin/bash

# Yet-Another-Blog Deployment Script
# This script safely updates and restarts the blog application

set -e  # Exit on error

# Check if running as root, if not, re-execute with sudo
if [ "$EUID" -ne 0 ]; then
    echo "Script requires root privileges. Re-executing with sudo..."
    exec sudo LOG="$LOG" "$0" "$@"
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SERVICE_NAME="Yet-Another-Blog"
LOG="${LOG:-FALSE}"  # Set LOG=TRUE to enable file logging
LOG_FILE="/var/log/yet-another-blog-update.log"
BACKUP_DIR="/tmp/blog-backup-$(date +%Y%m%d-%H%M%S)"
MIN_DISK_SPACE_MB=100  # Minimum disk space required for backup (in MB)

# Load port from .env if available
if [ -f ".env" ]; then
    PORT=$(grep "^PORT=" .env | cut -d '=' -f2)
fi
PORT="${PORT:-5000}"  # Default to 5000 if not set

# Application URL for health check (can be overridden with APP_URL env var)
APP_URL="${APP_URL:-http://localhost:$PORT}"

# Functions
log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
    [[ "$LOG" == "TRUE" ]] && echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE" 2>/dev/null || true
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] [ERROR]${NC} $1" >&2
    [[ "$LOG" == "TRUE" ]] && echo "[$(date +'%Y-%m-%d %H:%M:%S')] [ERROR] $1" >> "$LOG_FILE" 2>/dev/null || true
}

success() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] [SUCCESS]${NC} $1"
    [[ "$LOG" == "TRUE" ]] && echo "[$(date +'%Y-%m-%d %H:%M:%S')] [SUCCESS] $1" >> "$LOG_FILE" 2>/dev/null || true
}

warning() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] [WARNING]${NC} $1"
    [[ "$LOG" == "TRUE" ]] && echo "[$(date +'%Y-%m-%d %H:%M:%S')] [WARNING] $1" >> "$LOG_FILE" 2>/dev/null || true
}

# Check if git updates are available
check_git_updates() {
    log "Checking for updates from git..."

    # Fetch latest changes without modifying working directory
    if ! git fetch origin 2>/dev/null; then
        error "Failed to fetch from git remote"
        return 2  # Return 2 for fetch error
    fi

    # Get current branch
    local current_branch=$(git rev-parse --abbrev-ref HEAD)

    # Compare local and remote HEAD
    local local_commit=$(git rev-parse HEAD)
    local remote_commit=$(git rev-parse origin/"$current_branch" 2>/dev/null)

    if [ "$local_commit" = "$remote_commit" ]; then
        success "Already up to date (commit: ${local_commit:0:7})"
        return 1  # Return 1 for no updates
    else
        success "Updates available (local: ${local_commit:0:7}, remote: ${remote_commit:0:7})"
        return 0  # Return 0 for updates available
    fi
}

# Check if sufficient disk space is available
check_disk_space() {
    log "Checking available disk space..."
    local available_kb=$(df /tmp | tail -1 | awk '{print $4}')
    local available_mb=$((available_kb / 1024))
    local required_mb=$MIN_DISK_SPACE_MB

    if [ "$available_mb" -lt "$required_mb" ]; then
        error "Insufficient disk space for backup"
        error "Available: ${available_mb}MB, Required: ${required_mb}MB"
        return 1
    else
        success "Disk space check passed (${available_mb}MB available)"
        return 0
    fi
}

# Create backup of current version
create_backup() {
    log "Creating backup..."

    # Check disk space first
    if ! check_disk_space; then
        error "Cannot create backup due to insufficient disk space"
        return 1
    fi

    mkdir -p "$BACKUP_DIR"

    # Backup critical files
    if [ -f "app.py" ]; then
        cp -r . "$BACKUP_DIR/" 2>/dev/null || warning "Could not create full backup"
        success "Backup created at: $BACKUP_DIR"
    else
        warning "No app.py found, skipping backup"
    fi
}

# Check if service is running
check_service() {
    if service "$SERVICE_NAME" status >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# Stop the service
stop_service() {
    log "Stopping $SERVICE_NAME..."
    if check_service; then
        if service "$SERVICE_NAME" stop; then
            success "Service stopped successfully"
            sleep 2
        else
            error "Failed to stop service"
            return 1
        fi
    else
        warning "Service is not running"
    fi
}

# Pull latest changes
pull_updates() {
    log "Pulling latest changes from git..."

    # Check for uncommitted changes
    if ! git diff-index --quiet HEAD -- 2>/dev/null; then
        warning "You have uncommitted changes. Stashing them..."
        git stash save "Auto-stash before update $(date +'%Y-%m-%d %H:%M:%S')"
    fi

    # Pull changes
    if git pull; then
        success "Successfully pulled latest changes"
        return 0
    else
        error "Failed to pull changes from git"
        return 1
    fi
}

# Install/update dependencies if requirements.txt changed
update_dependencies() {
    if git diff HEAD@{1} HEAD --name-only | grep -q "requirements.txt"; then
        log "requirements.txt has changed, updating dependencies..."
        if [ -f "requirements.txt" ]; then
            # Assuming virtual environment
            if [ -d "venv" ]; then
                source venv/bin/activate
                pip install -r requirements.txt
                success "Dependencies updated"
            elif [ -d ".venv" ]; then
                source .venv/bin/activate
                pip install -r requirements.txt
                success "Dependencies updated"
            else
                warning "No virtual environment found, skipping dependency update"
            fi
        fi
    fi
}

# Start the service
start_service() {
    log "Starting $SERVICE_NAME..."
    if service "$SERVICE_NAME" start; then
        success "Service started successfully"
        sleep 3
        return 0
    else
        error "Failed to start service"
        return 1
    fi
}

# Check service status
check_status() {
    log "Checking service status..."
    if service "$SERVICE_NAME" status >/dev/null 2>&1; then
        success "Service is running properly"
        return 0
    else
        error "Service is not running correctly"
        return 1
    fi
}

# Health check - verify application is responding
health_check() {
    log "Performing application health check..."

    # Wait a moment for the app to fully start
    sleep 2

    # Check if curl is available
    if ! command -v curl &> /dev/null; then
        warning "curl not found, skipping health check"
        return 0
    fi

    # Try to reach the application (with 10 second timeout)
    local http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$APP_URL" 2>/dev/null)

    if [[ "$http_code" =~ ^(200|301|302|404)$ ]]; then
        success "Health check passed (HTTP $http_code)"
        return 0
    else
        error "Health check failed (HTTP ${http_code:-timeout})"
        error "Application may not be responding correctly at $APP_URL"
        return 1
    fi
}

# Rollback to backup if deployment fails
rollback() {
    error "Deployment failed! Rolling back to backup..."
    if [ -d "$BACKUP_DIR" ]; then
        cp -r "$BACKUP_DIR"/* . 2>/dev/null
        start_service
        warning "Rolled back to previous version from: $BACKUP_DIR"
    else
        error "No backup found, cannot rollback"
    fi
}

# Main deployment process
main() {
    log "=========================================="
    log "Starting deployment of $SERVICE_NAME"
    log "=========================================="

    # Check for git updates first
    check_git_updates
    local update_status=$?

    if [ $update_status -eq 1 ]; then
        log "=========================================="
        success "No deployment needed - already up to date!"
        log "=========================================="
        exit 0
    elif [ $update_status -eq 2 ]; then
        error "Git fetch failed. Cannot continue."
        exit 1
    fi

    # Create backup
    create_backup

    # Stop service
    if ! stop_service; then
        error "Cannot proceed with deployment"
        exit 1
    fi

    # Pull updates
    if ! pull_updates; then
        error "Git pull failed"
        start_service  # Try to restart with old code
        exit 1
    fi

    # Update dependencies if needed
    update_dependencies

    # Start service
    if ! start_service; then
        rollback
        exit 1
    fi

    # Check status
    if ! check_status; then
        rollback
        exit 1
    fi

    # Health check
    if ! health_check; then
        warning "Health check failed, but service is running"
        warning "You may need to investigate the application manually"
    fi

    log "=========================================="
    success "Deployment completed successfully!"
    log "=========================================="

    # Clean up old backups (keep last 5)
    log "Cleaning up old backups..."
    ls -dt /tmp/blog-backup-* 2>/dev/null | tail -n +6 | xargs rm -rf 2>/dev/null || true
}

# Run main function
main
