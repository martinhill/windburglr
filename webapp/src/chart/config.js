import { Chart } from 'chart.js/auto';
import 'chartjs-adapter-date-fns';
import { getDirectionText } from '../utils/time.js';
import { ZoomController } from './zoom.js';
import { store } from '../store/store.js';

export class ChartManager {
    constructor() {
        this.chart = null;
        this.zoomController = null;
        this.unsubscribeStore = null;
    }

    init() {
        const ctx = document.getElementById('windChart').getContext('2d');
        const state = store.getState();
        const isDarkMode = state.theme === 'dark';

        // Theme-aware colors for datasets
        const speedColor = isDarkMode ? '#60a5fa' : '#0ea5e9'; // blue-400 / sky-500
        const gustColor = isDarkMode ? '#f87171' : '#ef4444'; // red-400 / red-500
        const directionColor = isDarkMode ? '#fbbf24' : '#f59e0b'; // amber-400 / amber-500

        this.chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'Wind Speed (kts)',
                    data: [],
                    borderColor: speedColor,
                    backgroundColor: isDarkMode ? 'rgba(96, 165, 250, 0.2)' : 'rgba(14, 165, 233, 0.1)',
                    tension: 0.3,
                    fill: true,
                    yAxisID: 'y'
                }, {
                    label: 'Gust (kts)',
                    data: [],
                    borderColor: gustColor,
                    backgroundColor: isDarkMode ? 'rgba(248, 113, 113, 0.2)' : 'rgba(239, 68, 68, 0.1)',
                    tension: 0.1,
                    fill: false,
                    yAxisID: 'y'
                }, {
                    label: 'Wind Direction',
                    data: [],
                    borderColor: directionColor,
                    pointBackgroundColor: directionColor,
                    backgroundColor: directionColor,
                    fill: false,
                    yAxisID: 'y1',
                    showLine: false,
                    pointStyle: 'circle'
                }]
            },
            options: this.getChartOptions()
        });

        // Store chart instance in store
        store.setChartInstance(this.chart);

        this.zoomController = new ZoomController(this.chart);

        // Subscribe to store changes for automatic chart updates
        this.unsubscribeStore = store.subscribe((state, prevState, source) => {
            this.handleStateChange(state, prevState, source);
        });

        return this.chart;
    }

    getChartOptions() {
        const state = store.getState();
        const isDarkMode = state.theme === 'dark';

        // Theme-aware colors
        const textColor = isDarkMode ? '#f1f5f9' : '#374151';
        const gridColor = isDarkMode ? '#475569' : '#e2e8f0';
        const borderColor = isDarkMode ? '#334155' : '#d1d5db';

        return {
            pointStyle: false,
            responsive: true,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'minute',
                        stepSize: 15,
                        displayFormats: {
                            minute: 'HH:mm'
                        }
                    },
                    ticks: {
                        maxTicksLimit: 96,
                        autoSkip: false,
                        source: 'auto',
                        color: textColor,
                        callback: (value, index, values) => {
                            const date = new Date(value);
                            const minutes = date.getMinutes();
                            if (minutes % 15 === 0) {
                                if (!state.config.isLive && state.config.stationTimezone) {
                                    return date.toLocaleTimeString('en-US', {
                                        timeZone: state.config.stationTimezone,
                                        hour: '2-digit',
                                        minute: '2-digit',
                                        hour12: false
                                    });
                                } else {
                                    return date.toLocaleTimeString('en-US', {
                                        hour: '2-digit',
                                        minute: '2-digit',
                                        hour12: false
                                    });
                                }
                            }
                            return null;
                        }
                    },
                    grid: {
                        color: gridColor,
                        borderColor: borderColor
                    },
                    border: {
                        color: borderColor
                    }
                },
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Speed (knots)',
                        color: textColor
                    },
                    ticks: {
                        color: textColor
                    },
                    grid: {
                        color: gridColor,
                        borderColor: borderColor
                    },
                    border: {
                        color: borderColor
                    }
                },
                y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    min: 0,
                    max: 360,
                    title: {
                        display: true,
                        text: 'Direction',
                        color: textColor
                    },
                    ticks: {
                        stepSize: 45,
                        color: textColor,
                        callback: function(value) {
                            return getDirectionText(value);
                        }
                    },
                    grid: {
                        color: gridColor,
                        borderColor: borderColor,
                        drawOnChartArea: false,
                    },
                    border: {
                        color: borderColor
                    }
                }
            },
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: textColor,
                        // usePointStyle: true,
                        padding: 20
                    }
                },
                tooltip: {
                    enabled: false
                }
            },
            backgroundColor: isDarkMode ? '#1e293b' : '#ffffff'
        };
    }

    /**
     * Handle store state changes
     */
    handleStateChange(state, prevState, source) {
        // Update chart when wind data changes
        if (state.windData !== prevState.windData) {
            this.updateChart();
        }

        // Update loading indicator
        if (state.isLoading !== prevState.isLoading) {
            this.updateLoadingIndicator(state.isLoading);
        }

        // Handle zoom changes
        if (state.zoomRange !== prevState.zoomRange) {
            this.handleZoomChange(state.zoomRange);
        }

        // Update chart theme when theme changes
        if (state.theme !== prevState.theme) {
            this.updateChartTheme(state.theme);
        }
    }

    /**
     * Update chart with current store data
     */
    updateChart() {
        const chartData = store.getChartData();

        this.chart.data.labels = chartData.timeData;
        this.chart.data.datasets[0].data = chartData.speeds;
        this.chart.data.datasets[1].data = chartData.gusts;
        this.chart.data.datasets[2].data = chartData.directions;

        if (this.zoomController) {
            this.zoomController.onDataUpdate();
        }

        this.chart.update();
    }

    /**
     * Update loading indicator
     */
    updateLoadingIndicator(isLoading) {
        const loadingIndicator = document.getElementById('loading-indicator');
        if (loadingIndicator) {
            if (isLoading) {
                loadingIndicator.style.display = 'flex';
                loadingIndicator.classList.remove('fade-out');
            } else {
                loadingIndicator.classList.add('fade-out');
            }
        }
    }

    /**
     * Handle zoom range changes from store
     */
    handleZoomChange(zoomRange) {
        if (zoomRange) {
            this.chart.options.scales.x.min = zoomRange.min;
            this.chart.options.scales.x.max = zoomRange.max;
        } else {
            delete this.chart.options.scales.x.min;
            delete this.chart.options.scales.x.max;
        }
        this.chart.update();
    }

    /**
     * Update chart theme when dark/light mode changes
     */
    updateChartTheme(theme) {
        const isDarkMode = theme === 'dark';

        // Theme-aware colors
        const textColor = isDarkMode ? '#f1f5f9' : '#374151';
        const gridColor = isDarkMode ? '#475569' : '#e2e8f0';
        const borderColor = isDarkMode ? '#334155' : '#d1d5db';

        // Theme-aware dataset colors
        const speedColor = isDarkMode ? '#60a5fa' : '#0ea5e9'; // blue-400 / sky-500
        const gustColor = isDarkMode ? '#f87171' : '#ef4444'; // red-400 / red-500
        const directionColor = isDarkMode ? '#fbbf24' : '#f59e0b'; // amber-400 / amber-500

        // Update dataset colors
        this.chart.data.datasets[0].borderColor = speedColor;
        this.chart.data.datasets[0].backgroundColor = isDarkMode ? 'rgba(96, 165, 250, 0.2)' : 'rgba(14, 165, 233, 0.1)';

        this.chart.data.datasets[1].borderColor = gustColor;
        this.chart.data.datasets[1].backgroundColor = isDarkMode ? 'rgba(248, 113, 113, 0.2)' : 'rgba(239, 68, 68, 0.1)';

        this.chart.data.datasets[2].borderColor = directionColor;
        this.chart.data.datasets[2].pointBackgroundColor = directionColor;

        // Update scales
        this.chart.options.scales.x.ticks.color = textColor;
        this.chart.options.scales.x.grid.color = gridColor;
        this.chart.options.scales.x.border.color = borderColor;

        this.chart.options.scales.y.ticks.color = textColor;
        this.chart.options.scales.y.title.color = textColor;
        this.chart.options.scales.y.grid.color = gridColor;
        this.chart.options.scales.y.border.color = borderColor;

        this.chart.options.scales.y1.ticks.color = textColor;
        this.chart.options.scales.y1.title.color = textColor;
        this.chart.options.scales.y1.grid.color = gridColor;
        this.chart.options.scales.y1.border.color = borderColor;

        // Update legend
        this.chart.options.plugins.legend.labels.color = textColor;

        // Update chart background
        this.chart.canvas.parentNode.style.backgroundColor = isDarkMode ? '#1e293b' : '#ffffff';

        this.chart.update();
    }

    /**
     * Get last observation time from store
     */
    getLastObservationTime() {
        return store.getState().lastObservationTime;
    }

    /**
     * Cleanup method
     */
    destroy() {
        if (this.unsubscribeStore) {
            this.unsubscribeStore();
        }
        if (this.zoomController) {
            // Add cleanup method to zoom controller if needed
        }
        if (this.chart) {
            this.chart.destroy();
        }
    }
}
