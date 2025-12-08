// Test file with mixed documentation styles

/// Doxygen single-line style
class DoxygenClass {
public:
    /** JavaDoc style method */
    void javaDocMethod();

    /*! Qt style method */
    void qtMethod();
};

/**
 * @brief JavaDoc multi-line for class
 */
class JavaDocClass {
public:
    /// Doxygen style method
    void doxygenMethod();
};

/*! Qt style class */
class QtClass {
public:
    /**
     * @brief JavaDoc method in Qt class
     */
    void mixedMethod();
};
