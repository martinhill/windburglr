/**
 * Memorial popup functionality for Jason "Ghostrider" Maloney
 */

class MemorialPopupManager {
    constructor() {
        this.isInitialized = false;
        this.escKeyHandler = null;
        this.outsideClickHandler = null;
    }

    /**
     * Initialize the memorial popup functionality
     */
    init() {
        if (this.isInitialized) return;

        this.setupGlobalFunctions();
        this.setupEventListeners();
        this.isInitialized = true;

        console.log('✓ Memorial popup manager initialized');
    }

    /**
     * Set up global functions for template inline handlers
     */
    setupGlobalFunctions() {
        // Make memorial popup functions globally available for template inline handlers
        window.showMemorialPopup = this.showMemorialPopup.bind(this);
        window.dismissMemorialPopup = this.dismissMemorialPopup.bind(this);
    }

    /**
     * Set up event listeners for memorial popup buttons
     */
    setupEventListeners() {
        // Memorial popup event listeners
        const showMemorialBtn = document.getElementById('show-memorial');
        if (showMemorialBtn) {
            showMemorialBtn.addEventListener('click', (event) => {
                event.preventDefault();
                window.showMemorialPopup();
            });
        }

        const dismissMemorialBtn = document.getElementById('dismiss-memorial');
        if (dismissMemorialBtn) {
            dismissMemorialBtn.addEventListener('click', (event) => {
                event.preventDefault();
                window.dismissMemorialPopup();
            });
        }
    }

    /**
     * Show the memorial popup with lazy loading
     */
    showMemorialPopup(screenWidth = window.innerWidth) {
        const memorialPopup = document.getElementById('memorial');
        if (!memorialPopup) {
            console.error('Memorial popup element not found');
            return;
        }

        memorialPopup.classList.remove('hidden');

        // Add ESC key listener
        this.escKeyHandler = (event) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                this.dismissMemorialPopup();
            }
        };
        document.addEventListener('keydown', this.escKeyHandler);

        // Add outside click/touch listener
        this.outsideClickHandler = (event) => {
            // Close if clicked/touched outside the popup content
            if (event.target === memorialPopup) {
                event.preventDefault();
                this.dismissMemorialPopup();
            }
        };
        memorialPopup.addEventListener('click', this.outsideClickHandler);
        memorialPopup.addEventListener('touchstart', this.outsideClickHandler);

        // Lazy load image only when popup is shown
        const memorialImage = memorialPopup.querySelector('.memorial-image');
        if (memorialImage && !memorialImage.src) {
            // Set appropriate src based on screen size for lazy loading
            let imageSrc = '/static/ghostrider/ghostrider-large.jpg'; // default

            if (screenWidth <= 640) {
                imageSrc = '/static/ghostrider/ghostrider-small.jpg';
            } else if (screenWidth <= 1200) {
                imageSrc = '/static/ghostrider/ghostrider-medium.jpg';
            }

            // Add loading class for styling before setting src
            memorialImage.classList.add('loading');

            // Set the src to trigger loading
            memorialImage.src = imageSrc;
            memorialImage.setAttribute('data-loaded', 'true');

            // Remove loading class when image loads
            memorialImage.addEventListener('load', () => {
                memorialImage.classList.remove('loading');
                console.log('Memorial image loaded successfully');
            });

            // Handle loading errors
            memorialImage.addEventListener('error', () => {
                console.error('Failed to load memorial image');
                memorialImage.classList.remove('loading');
                memorialImage.classList.add('error');
            });
        }
    }

    /**
     * Dismiss the memorial popup
     */
    dismissMemorialPopup() {
        const memorialPopup = document.getElementById('memorial');
        if (memorialPopup) {
            memorialPopup.classList.add('hidden');

            // Remove event listeners
            if (this.escKeyHandler) {
                document.removeEventListener('keydown', this.escKeyHandler);
                this.escKeyHandler = null;
            }

            if (this.outsideClickHandler) {
                memorialPopup.removeEventListener('click', this.outsideClickHandler);
                memorialPopup.removeEventListener('touchstart', this.outsideClickHandler);
                this.outsideClickHandler = null;
            }
        }
    }

    /**
     * Cleanup method
     */
    destroy() {
        // Dismiss popup if open and clean up its event listeners
        this.dismissMemorialPopup();

        // Remove event listeners
        const showMemorialBtn = document.getElementById('show-memorial');
        if (showMemorialBtn) {
            showMemorialBtn.removeEventListener('click', window.showMemorialPopup);
        }

        const dismissMemorialBtn = document.getElementById('dismiss-memorial');
        if (dismissMemorialBtn) {
            dismissMemorialBtn.removeEventListener('click', window.dismissMemorialPopup);
        }

        // Remove global functions
        delete window.showMemorialPopup;
        delete window.dismissMemorialPopup;

        this.isInitialized = false;
        console.log('✓ Memorial popup manager destroyed');
    }
}

// Export the manager class
export { MemorialPopupManager };