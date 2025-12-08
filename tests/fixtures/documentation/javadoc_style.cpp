// Test file for JavaDoc-style documentation

/**
 * Database connection manager.
 */
class DatabaseManager {
public:
    /**
     * Establishes connection to database.
     * @param host Database server hostname
     * @param port Database server port
     * @return True if connection successful
     */
    bool connect(const char* host, int port);

    /**
     * Executes SQL query.
     */
    void* executeQuery(const char* sql);
};

/**
 * Logger for application events.
 *
 * Provides thread-safe logging with multiple severity levels.
 * Supports file and console output.
 */
class Logger {
public:
    /**
     * Logs an informational message.
     * @param message The message to log
     */
    void info(const char* message);

    /**
     * Logs an error message.
     * @param message The error message
     * @param code Error code
     */
    void error(const char* message, int code);
};
