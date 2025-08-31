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

        this.chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'Wind Speed (kts)',
                    data: [],
                    borderColor: 'rgb(0, 168, 240)',
                    backgroundColor: 'rgba(0, 168, 240, 0.1)',
                    tension: 0.3,
                    fill: true,
                    yAxisID: 'y'
                }, {
                    label: 'Gust (kts)',
                    data: [],
                    borderColor: 'rgb(255, 99, 132)',
                    backgroundColor: 'rgba(255, 99, 132, 0.1)',
                    tension: 0.1,
                    fill: false,
                    yAxisID: 'y'
                }, {
                    label: 'Wind Direction',
                    data: [],
                    borderColor: 'orange',
                    pointBackgroundColor: 'orange',
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
                    }
                },
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Speed (knots)'
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
                        text: 'Direction'
                    },
                    ticks: {
                        stepSize: 45,
                        callback: function(value) {
                            return getDirectionText(value);
                        }
                    },
                    grid: {
                        drawOnChartArea: false,
                    },
                }
            },
            plugins: {
                legend: {
                    position: 'bottom'
                },
                tooltip: {
                    enabled: false
                }
            }
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