// Test fixture for basic call site extraction
// Tests: CS-01 (basic), CS-02 (multiple calls), CS-03 (control flow)

void helper() {
    // Empty function for testing
}

void validate() {
    // Another empty function
}

// Test CS-01: Basic call site tracking
void single_caller() {
    helper();  // Line 14 - single call
}

// Test CS-02: Multiple calls to same function
void multiple_calls() {
    validate();  // Line 19 - first call
    int x = 0;
    validate();  // Line 21 - second call to same function
}

// Test CS-03: Calls in different control flow paths
void conditional_calls(bool flag) {
    if (flag) {
        helper();  // Line 27 - call in if branch
    } else {
        helper();  // Line 29 - call in else branch
    }
}

// Test CS-04: Method calls (will be tested in separate fixture)
class Processor {
public:
    void validate() {
        // Member function
    }

    void process() {
        validate();  // Line 41 - member function call
        helper();    // Line 42 - free function call
    }
};

// Test CS-07: Recursive calls
void recursive(int n) {
    if (n > 0) {
        recursive(n - 1);  // Line 49 - recursive call
    }
}

// Test: Nested function calls
void nested_calls() {
    validate();          // Line 56
    helper();            // Line 57
}
