// Test file for Qt-style documentation

/*! Widget for displaying user interface elements */
class Widget {
public:
    /*! Shows the widget on screen */
    void show();

    /*! Hides the widget from view */
    void hide();
};

/*!
 * \brief Event handler for user interactions
 *
 * Processes mouse clicks, keyboard input, and touch events.
 * Uses Qt signal-slot mechanism for event propagation.
 */
class EventHandler {
public:
    /*!
     * \brief Handles mouse click events
     * \param x X coordinate of click
     * \param y Y coordinate of click
     */
    void onMouseClick(int x, int y);
};

/*! Network socket for TCP/IP communication */
class Socket {
public:
    /*! Opens connection to remote host */
    bool open(const char* host);
};
