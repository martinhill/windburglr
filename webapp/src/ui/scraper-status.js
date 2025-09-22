export class ScraperStatusManager {
    constructor() {
        this.currentStatus = null;
        this.statusElement = null;
        this.bannerElement = null;
        this.setupElements();
        this.setupEventListeners();
    }

    setupElements() {
        this.statusElement = document.getElementById('scraper-status');
        this.bannerElement = document.getElementById('status-banner');

        if (!this.statusElement) {
            console.warn('Scraper status element not found');
            return;
        }
    }

    setupEventListeners() {
        if (this.statusElement) {
            this.statusElement.addEventListener('click', () => {
                this.toggleBanner();
            });
        }

        // Close banner when clicking close button
        const closeButton = document.getElementById('status-banner-close');
        if (closeButton) {
            closeButton.addEventListener('click', () => {
                this.hideBanner();
            });
        }

        // Close banner when clicking outside
        if (this.bannerElement) {
            document.addEventListener('click', (e) => {
                if (!this.bannerElement.contains(e.target) &&
                    !this.statusElement.contains(e.target) &&
                    this.bannerElement.classList.contains('visible')) {
                    this.hideBanner();
                }
            });
        }
    }

    updateStatus(statusData) {
        this.currentStatus = statusData;
        this.updateStatusDisplay();
        this.updateBannerContent();
    }

    updateStatusDisplay() {
        if (!this.statusElement || !this.currentStatus) return;

        const status = this.currentStatus.status;
        const humanText = this.getHumanReadableStatus(status);

        // Update text content
        this.statusElement.textContent = humanText;

        // Remove all status classes
        this.statusElement.className = this.statusElement.className
            .replace(/\b(hidden|healthy|warning|error|stopped)\b/g, '');

        // Add appropriate class based on status
        if (status === 'healthy') {
            this.statusElement.classList.add('healthy');
        } else if (status === 'stopped') {
            this.statusElement.classList.add('stopped');
        } else if (['stale_data', 'unknown'].includes(status)) {
            this.statusElement.classList.add('warning');
        } else {
            // http_error, parse_error, network_error, error, or any other non-healthy status
            this.statusElement.classList.add('error');
        }
    }

    getHumanReadableStatus(status) {
        const statusMap = {
            'healthy': 'OK',
            'stale_data': 'Stale Data',
            'http_error': 'HTTP Error',
            'parse_error': 'Parse Error',
            'network_error': 'Network Error',
            'error': 'Error',
            'unknown': 'Unknown',
            'stopped': 'Stopped'
        };

        return statusMap[status] || status;
    }

    formatDurationSeconds(totalSeconds) {
        if (totalSeconds < 0) {
            return 'Unknown';
        }

        const days = Math.floor(totalSeconds / 86400);
        const hours = Math.floor((totalSeconds % 86400) / 3600);
        const minutes = Math.floor((totalSeconds % 3600) / 60);
        const seconds = totalSeconds % 60;

        const parts = [];
        if (days > 0) parts.push(`${days}d`);
        if (hours > 0) parts.push(`${hours}h`);
        if (minutes > 0) parts.push(`${minutes}m`);
        if (seconds > 0 || parts.length === 0) parts.push(`${seconds}s`);

        // Return the most significant parts (max 2 units for readability)
        return parts.slice(0, 2).join(' ');
    }

    formatElapsedTime(timestamp) {
        if (!timestamp) return 'Unknown';

        try {
            const pastDate = new Date(timestamp);
            if (isNaN(pastDate.getTime())) {
                return 'Invalid date';
            }

            const now = new Date();
            const elapsedMs = now.getTime() - pastDate.getTime();
            const elapsedSeconds = Math.floor(elapsedMs / 1000);

            if (elapsedSeconds < 0) {
                return 'just now';
            }

            return this.formatDurationSeconds(elapsedSeconds);
        } catch (e) {
            return String(timestamp);
        }
    }

    updateBannerContent() {
        if (!this.bannerElement || !this.currentStatus) return;

        const status = this.currentStatus;
        const bannerContent = this.bannerElement.querySelector('.status-banner-details');

        if (!bannerContent) return;

        const formatTime = (dateStr) => {
            if (!dateStr) return 'Never';
            const date = new Date(dateStr);
            return date.toLocaleString();
        };



        const formatDuration = (duration) => {
            if (!duration) return 'Unknown';

            let totalSeconds;

            // Handle different duration formats
            if (typeof duration === 'object' && duration.days !== undefined) {
                // Python timedelta object format
                totalSeconds = (duration.days * 86400) + (duration.seconds || 0);
            } else if (typeof duration === 'string') {
                // Could be ISO timestamp string - treat as elapsed time from that timestamp
                return formatElapsedTime(duration);
            } else if (typeof duration === 'number') {
                // Already in seconds
                totalSeconds = Math.floor(duration);
            } else {
                return String(duration);
            }

            return this.formatDurationSeconds(totalSeconds);
        };

        bannerContent.innerHTML = `
            <div class="status-detail">
                <div class="status-detail-label">Station</div>
                <div class="status-detail-value">${status.station_name || 'Unknown'}</div>
            </div>
            <div class="status-detail">
                <div class="status-detail-label">Status</div>
                <div class="status-detail-value">${this.getHumanReadableStatus(status.status)}</div>
            </div>
            <div class="status-detail">
                <div class="status-detail-label">Retry Count</div>
                <div class="status-detail-value">${status.retry_count || 0}</div>
            </div>
            <div class="status-detail">
                <div class="status-detail-label">Last Success</div>
                <div class="status-detail-value">${status.last_success ? `${formatTime(status.last_success)} (${this.formatElapsedTime(status.last_success)})` : 'Never'}</div>
            </div>
            <div class="status-detail">
                <div class="status-detail-label">Last Attempt</div>
                <div class="status-detail-value">${status.last_attempt ? `${formatTime(status.last_attempt)} (${this.formatElapsedTime(status.last_attempt)})` : 'Never'}</div>
            </div>
            ${status.error_message ? `
            <div class="status-detail" style="grid-column: 1 / -1;">
                <div class="status-detail-label">Error Message</div>
                <div class="status-detail-value error-message">${status.error_message}</div>
            </div>
            ` : ''}
        `;
    }

    toggleBanner() {
        if (!this.bannerElement) return;

        if (this.bannerElement.classList.contains('visible')) {
            this.hideBanner();
        } else {
            this.showBanner();
        }
    }

    showBanner() {
        if (this.bannerElement) {
            this.bannerElement.classList.add('visible');
        }
    }

    hideBanner() {
        if (this.bannerElement) {
            this.bannerElement.classList.remove('visible');
        }
    }

    destroy() {
        // Cleanup event listeners if needed
        this.currentStatus = null;
        this.statusElement = null;
        this.bannerElement = null;
    }
}
