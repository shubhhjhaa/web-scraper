"""
Manual stealth patches for Playwright to bypass bot detection.
This replaces the broken playwright-stealth package with custom JS injections.
"""

# These scripts are injected before any page navigation to mask automation signals.

STEALTH_SCRIPTS = [
    # 1. Hide navigator.webdriver
    """
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined
    });
    """,

    # 2. Pass Chrome check (chrome object)
    """
    window.chrome = {
        runtime: {},
        loadTimes: function() {},
        csi: function() {},
        app: {}
    };
    """,

    # 3. Fix permissions query (Notification)
    """
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
    );
    """,

    # 4. Override plugins (headless has 0 plugins)
    """
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5]
    });
    """,

    # 5. Override languages
    """
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en', 'hi']
    });
    """,

    # 6. Fix WebGL vendor/renderer
    """
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Intel Inc.';
        if (parameter === 37446) return 'Intel Iris OpenGL Engine';
        return getParameter.call(this, parameter);
    };
    """,

    # 7. Override navigator.platform
    """
    Object.defineProperty(navigator, 'platform', {
        get: () => 'Win32'
    });
    """,

    # 8. Fix broken hairline feature detection
    """
    Object.defineProperty(navigator, 'hardwareConcurrency', {
        get: () => 4
    });
    """,

    # 9. Fix connection.rtt (headless returns 0)
    """
    if (navigator.connection) {
        Object.defineProperty(navigator.connection, 'rtt', {
            get: () => 100
        });
    }
    """,

    # 10. Prevent iframe contentWindow detection
    """
    try {
        const originalAttachShadow = Element.prototype.attachShadow;
        Element.prototype.attachShadow = function() {
            return originalAttachShadow.call(this, ...arguments);
        };
    } catch(e) {}
    """,
]


def apply_stealth(page) -> None:
    """
    Applies all stealth patches to a Playwright page via init scripts.
    Call this BEFORE navigating to any URL.
    """
    for script in STEALTH_SCRIPTS:
        page.add_init_script(script)
