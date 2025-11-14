// This file intentionally has syntax errors for testing error handling

class IncompleteClass {
public:
    void method()  // Missing semicolon and body

    int value  // Missing semicolon

// Missing closing brace

void orphanedFunction( {
    // Mismatched brackets
}

template<typename T
class BrokenTemplate {  // Missing closing angle bracket
    T data;
};
