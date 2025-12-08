// Test file for Doxygen-style documentation

/// Parses C++ source files and extracts symbols
class Parser {
public:
    /// Initializes the parser with default settings
    Parser();

    /// Parses a single source file
    /// @param filename Path to the source file
    /// @return True if parsing succeeded
    bool parse(const char* filename);
};

/**
 * @brief Manages HTTP request handling
 *
 * This class provides comprehensive HTTP request processing.
 * It supports:
 * - GET and POST methods
 * - Header parsing
 * - Cookie management
 *
 * @see Response for output handling
 * @note Thread-safe for concurrent requests
 */
class RequestHandler {
public:
    /**
     * @brief Processes an incoming HTTP request
     * @param request The HTTP request object
     * @return Response object with status and data
     */
    void* processRequest(void* request);
};

/// Stores application configuration settings
///
/// This class loads configuration from JSON files
/// and provides type-safe access to settings.
class Config {
public:
    /// Loads configuration from file
    void load(const char* path);
};
