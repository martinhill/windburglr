import { store } from '../store/store.js';

export class ZoomController {
    constructor(chart) {
        this.chart = chart;
        this.isZooming = false;
        this.zoomStartX = null;
        this.zoomOverlay = null;
        this.setupZoomOverlay();
        this.setupEventListeners();
    }

    setupZoomOverlay() {
        const canvas = document.getElementById('windChart');
        if (!canvas) {
            console.error('ZoomController: Canvas element not found');
            return;
        }
        const rect = canvas.getBoundingClientRect();

        // Remove any existing zoom overlay to prevent duplicates
        const existingOverlay = canvas.parentElement.querySelector('.zoom-overlay');
        if (existingOverlay) {
            existingOverlay.remove();
        }

        this.zoomOverlay = document.createElement('div');
        this.zoomOverlay.className = 'zoom-overlay'; // Add class for easier identification
        this.zoomOverlay.style.position = 'absolute';
        this.zoomOverlay.style.backgroundColor = 'rgba(102, 126, 234, 0.2)';
        this.zoomOverlay.style.border = '1px solid rgba(102, 126, 234, 0.5)';
        this.zoomOverlay.style.pointerEvents = 'none';
        this.zoomOverlay.style.zIndex = '1000';
        this.zoomOverlay.style.display = 'none';
        this.zoomOverlay.style.marginTop = '1em';
        this.zoomOverlay.style.minHeight = '70%';

        canvas.parentElement.style.position = 'relative';
        canvas.parentElement.appendChild(this.zoomOverlay);
    }

    updateZoomOverlay(startX, currentX) {
        if (!this.zoomOverlay) return;

        const canvas = document.getElementById('windChart');
        const canvasRect = canvas.getBoundingClientRect();
        const parentRect = canvas.parentElement.getBoundingClientRect();
        const chartArea = this.chart.chartArea;

        const left = Math.min(startX, currentX);
        const width = Math.abs(currentX - startX);

        // Calculate position relative to the parent element (chart-section)
        this.zoomOverlay.style.left = `${left - parentRect.left}px`;
        this.zoomOverlay.style.top = `${chartArea.top}px`;
        this.zoomOverlay.style.width = `${width}px`;
        this.zoomOverlay.style.height = `${canvasRect.height - canvasRect.top + parentRect.top - chartArea.top}px`;
        this.zoomOverlay.style.display = 'block';
    }

    hideZoomOverlay() {
        if (this.zoomOverlay) {
            this.zoomOverlay.style.display = 'none';
        }
    }

    performZoom(startX, endX) {
        const canvas = document.getElementById('windChart');
        const canvasRect = canvas.getBoundingClientRect();

        const startDataX = this.chart.scales.x.getValueForPixel(startX - canvasRect.left);
        const endDataX = this.chart.scales.x.getValueForPixel(endX - canvasRect.left);

        if (!startDataX || !endDataX) return;

        const state = store.getState();
        let originalTimeRange = state.originalTimeRange;

        if (!originalTimeRange && this.chart.data.labels.length > 0) {
            originalTimeRange = {
                min: this.chart.data.labels[0],
                max: this.chart.data.labels[this.chart.data.labels.length - 1]
            };
        }

        const minTime = Math.min(startDataX, endDataX);
        const maxTime = Math.max(startDataX, endDataX);

        // Update zoom range in store
        store.setZoomRange({
            min: minTime,
            max: maxTime
        }, originalTimeRange);

        const resetButton = document.getElementById('reset-zoom');
        if (resetButton) {
            resetButton.style.display = 'inline-block';
        }
    }

    resetZoom() {
        // Reset zoom in store (will be handled by ChartManager)
        store.resetZoom();

        const resetButton = document.getElementById('reset-zoom');
        if (resetButton) {
            resetButton.style.display = 'none';
        }
    }

    onDataUpdate() {
        // Reset zoom state when new data is loaded
        store.resetZoom();

        const resetButton = document.getElementById('reset-zoom');
        if (resetButton) {
            resetButton.style.display = 'none';
        }
    }

    setupEventListeners() {
        const canvas = document.getElementById('windChart');
        if (!canvas) {
            console.error('ZoomController: Canvas element not found');
            return;
        }

        const handleStart = (e) => {
            const canvasRect = canvas.getBoundingClientRect();
            const x = e.clientX || (e.touches && e.touches[0].clientX);
            const y = e.clientY || (e.touches && e.touches[0].clientY);
            const chartArea = this.chart.chartArea;

            if (x >= canvasRect.left + chartArea.left && x <= canvasRect.left + chartArea.right &&
                y >= canvasRect.top + chartArea.top && y <= canvasRect.bottom - 100) {
                this.isZooming = true;
                this.zoomStartX = x;
                canvas.style.cursor = 'zoom-in';
                e.preventDefault();
            }
        };

        const handleMove = (e) => {
            if (this.isZooming && this.zoomStartX !== null) {
                const x = e.clientX || (e.touches && e.touches[0].clientX);
                this.updateZoomOverlay(this.zoomStartX, x);
            }
        };

        const handleEnd = (e) => {
            if (this.isZooming && this.zoomStartX !== null) {
                const x = e.clientX || (e.changedTouches && e.changedTouches[0].clientX);
                const minDragDistance = 20;

                if (Math.abs(x - this.zoomStartX) > minDragDistance) {
                    this.performZoom(this.zoomStartX, x);
                }

                this.isZooming = false;
                this.zoomStartX = null;
                this.hideZoomOverlay();
                canvas.style.cursor = 'default';
            }
        };

        const handleCancel = () => {
            if (this.isZooming) {
                this.isZooming = false;
                this.zoomStartX = null;
                this.hideZoomOverlay();
                canvas.style.cursor = 'default';
            }
        };

        canvas.addEventListener('mousedown', handleStart);
        canvas.addEventListener('mousemove', handleMove);
        canvas.addEventListener('mouseup', handleEnd);
        canvas.addEventListener('mouseleave', handleCancel);

        canvas.addEventListener('touchstart', (e) => handleStart(e));
        canvas.addEventListener('touchmove', (e) => {
            e.preventDefault();
            handleMove(e);
        });
        canvas.addEventListener('touchend', (e) => {
            e.preventDefault();
            handleEnd(e);
        });
        canvas.addEventListener('touchcancel', (e) => {
            e.preventDefault();
            handleCancel();
        });

        canvas.addEventListener('dblclick', () => this.resetZoom());

        let lastTap = 0;
        canvas.addEventListener('touchend', (e) => {
            const currentTime = new Date().getTime();
            const tapLength = currentTime - lastTap;
            if (tapLength < 500 && tapLength > 0) {
                e.preventDefault();
                this.resetZoom();
            }
            lastTap = currentTime;
        });

        const resetButton = document.getElementById('reset-zoom');
        if (resetButton) {
            resetButton.addEventListener('click', () => this.resetZoom());
        }
    }
}
