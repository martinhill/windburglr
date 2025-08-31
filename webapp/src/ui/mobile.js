export function isMobileDevice() {
    return window.innerWidth <= 480 && 'ontouchstart' in window;
}

export function isPortraitOrientation() {
    return window.innerHeight > window.innerWidth;
}

export function hasSeenOrientationPopup() {
    return localStorage.getItem('windburglr-orientation-popup-seen') === 'true';
}

export function markOrientationPopupSeen() {
    localStorage.setItem('windburglr-orientation-popup-seen', 'true');
}

export function showOrientationPopup() {
    const popup = document.getElementById('orientation-popup');
    if (popup) {
        popup.classList.remove('hidden');
    }
}

export function hideOrientationPopup() {
    const popup = document.getElementById('orientation-popup');
    if (popup) {
        popup.classList.add('hidden');
    }
}

export function dismissOrientationPopup() {
    hideOrientationPopup();
    markOrientationPopupSeen();
}

export function checkOrientationPopup() {
    if (isMobileDevice() && isPortraitOrientation() && !hasSeenOrientationPopup()) {
        setTimeout(showOrientationPopup, 1000);
    }
}

export function setupOrientationHandlers() {
    window.addEventListener('orientationchange', function() {
        setTimeout(function() {
            if (!isPortraitOrientation()) {
                hideOrientationPopup();
            }
        }, 500);
    });

    window.addEventListener('resize', function() {
        if (!isPortraitOrientation()) {
            hideOrientationPopup();
        }
    });
}