/**
 * Test file for MemorialPopupManager lazy loading functionality
 */

import { vi } from 'vitest';

// Mock DOM elements for testing
const mockImage = {
    src: '',
    classList: {
        add: vi.fn(),
        remove: vi.fn()
    },
    addEventListener: vi.fn(),
    setAttribute: vi.fn(),
    hasAttribute: vi.fn().mockReturnValue(false)
};

const mockPopup = {
    classList: {
        remove: vi.fn(),
        add: vi.fn()
    },
    querySelector: vi.fn().mockReturnValue(mockImage),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn()
};

// Mock document.getElementById
global.document = {
    getElementById: vi.fn().mockReturnValue(mockPopup),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn()
};

// Mock window object
global.window = {
    innerWidth: 1024,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn()
};

// Import the module to test
import { MemorialPopupManager } from './ghostrider.js';

describe('MemorialPopupManager', () => {
    let manager;

    beforeEach(() => {
        // Reset mock image state
        mockImage.src = '';
        mockImage.hasAttribute.mockReturnValue(false);
        manager = new MemorialPopupManager();
        vi.clearAllMocks();
    });

    test('should lazy load image when popup is shown', () => {
        // Initially, image should have no src
        expect(mockImage.src).toBe('');

        // Show popup
        manager.showMemorialPopup();

        // Image src should now be set based on screen size
        expect(mockImage.src).toBe('/static/ghostrider/ghostrider-medium.jpg');
        expect(mockImage.classList.add).toHaveBeenCalledWith('loading');
        expect(mockImage.setAttribute).toHaveBeenCalledWith('data-loaded', 'true');
    });

    test('should use small image for mobile screens', () => {
        // Test with mobile screen width
        manager.showMemorialPopup(400);

        expect(mockImage.src).toBe('/static/ghostrider/ghostrider-small.jpg');
    });

    test('should use medium image for standard desktop screens', () => {
        // Test with standard desktop screen width
        manager.showMemorialPopup(1200);

        expect(mockImage.src).toBe('/static/ghostrider/ghostrider-medium.jpg');
    });

    test('should use large image for large desktop screens', () => {
        // Test with large desktop screen width
        manager.showMemorialPopup(1400);

        expect(mockImage.src).toBe('/static/ghostrider/ghostrider-large.jpg');
    });

    test('should not reload image if already loaded', () => {
        // Set up image as already loaded
        mockImage.src = '/static/ghostrider/ghostrider-large.jpg';
        mockImage.hasAttribute.mockReturnValue(true);

        manager.showMemorialPopup();

        // Should not change src or add loading class
        expect(mockImage.classList.add).not.toHaveBeenCalledWith('loading');
    });

    test('should add ESC key and outside click listeners when popup is shown', () => {
        manager.showMemorialPopup();

        // Should add ESC key listener to document
        expect(global.document.addEventListener).toHaveBeenCalledWith('keydown', expect.any(Function));

        // Should add click and touchstart listeners to popup
        expect(mockPopup.addEventListener).toHaveBeenCalledWith('click', expect.any(Function));
        expect(mockPopup.addEventListener).toHaveBeenCalledWith('touchstart', expect.any(Function));
    });

    test('should close popup when ESC key is pressed', () => {
        manager.showMemorialPopup();

        // Get the ESC key handler that was added
        const escHandler = global.document.addEventListener.mock.calls.find(
            call => call[0] === 'keydown'
        )[1];

        // Simulate ESC key press
        const escEvent = { key: 'Escape', preventDefault: vi.fn() };
        escHandler(escEvent);

        // Should prevent default and hide the popup
        expect(escEvent.preventDefault).toHaveBeenCalled();
        expect(mockPopup.classList.add).toHaveBeenCalledWith('hidden');
    });

    test('should not close popup when other keys are pressed', () => {
        manager.showMemorialPopup();

        // Get the ESC key handler that was added
        const escHandler = global.document.addEventListener.mock.calls.find(
            call => call[0] === 'keydown'
        )[1];

        // Simulate other key press
        const otherEvent = { key: 'Enter', preventDefault: vi.fn() };
        escHandler(otherEvent);

        // Should not prevent default or hide the popup
        expect(otherEvent.preventDefault).not.toHaveBeenCalled();
        expect(mockPopup.classList.add).not.toHaveBeenCalledWith('hidden');
    });

    test('should close popup when clicking outside content area', () => {
        manager.showMemorialPopup();

        // Get the outside click handler that was added
        const clickHandler = mockPopup.addEventListener.mock.calls.find(
            call => call[0] === 'click'
        )[1];

        // Simulate click on popup background (outside content)
        const clickEvent = { target: mockPopup, preventDefault: vi.fn() };
        clickHandler(clickEvent);

        // Should prevent default and hide the popup
        expect(clickEvent.preventDefault).toHaveBeenCalled();
        expect(mockPopup.classList.add).toHaveBeenCalledWith('hidden');
    });

    test('should not close popup when clicking on content area', () => {
        manager.showMemorialPopup();

        // Get the outside click handler that was added
        const clickHandler = mockPopup.addEventListener.mock.calls.find(
            call => call[0] === 'click'
        )[1];

        // Simulate click on content area (not the popup itself)
        const contentElement = { className: 'memorial-popup-content' };
        const clickEvent = { target: contentElement, preventDefault: vi.fn() };
        clickHandler(clickEvent);

        // Should not prevent default or hide the popup
        expect(clickEvent.preventDefault).not.toHaveBeenCalled();
        expect(mockPopup.classList.add).not.toHaveBeenCalledWith('hidden');
    });

    test('should remove event listeners when popup is dismissed', () => {
        manager.showMemorialPopup();
        manager.dismissMemorialPopup();

        // Should remove ESC key listener from document
        expect(global.document.removeEventListener).toHaveBeenCalledWith('keydown', expect.any(Function));

        // Should remove click and touchstart listeners from popup
        expect(mockPopup.removeEventListener).toHaveBeenCalledWith('click', expect.any(Function));
        expect(mockPopup.removeEventListener).toHaveBeenCalledWith('touchstart', expect.any(Function));
    });

    test('should handle touch events the same as click events', () => {
        manager.showMemorialPopup();

        // Get the touch handler that was added
        const touchHandler = mockPopup.addEventListener.mock.calls.find(
            call => call[0] === 'touchstart'
        )[1];

        // Simulate touch on popup background
        const touchEvent = { target: mockPopup, preventDefault: vi.fn() };
        touchHandler(touchEvent);

        // Should prevent default and hide the popup
        expect(touchEvent.preventDefault).toHaveBeenCalled();
        expect(mockPopup.classList.add).toHaveBeenCalledWith('hidden');
    });
});