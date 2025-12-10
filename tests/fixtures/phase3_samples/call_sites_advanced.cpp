// Test fixture for advanced call site scenarios
// Tests: CS-05 (function pointers), CS-06 (lambdas), CS-08 (templates)

void callback_func() {
    // Callback function
}

void external_func() {
    // External function
}

// Test CS-05: Function pointers vs direct calls
void function_pointer_test() {
    // Assignment is NOT a call (should not be tracked)
    auto fn = callback_func;

    // This IS a call via function pointer (should be tracked)
    fn();                   // Line 18

    // Direct call (should be tracked)
    callback_func();        // Line 21
}

// Test CS-06: Lambda captures and calls
void lambda_test() {
    auto lambda = []() {
        external_func();    // Line 27 - call from lambda
    };

    lambda();               // Line 30 - lambda invocation
}

// Test CS-08: Template function calls
template<typename T>
void process_template(T value) {
    // Template function
}

void template_caller() {
    process_template<int>(42);      // Line 40
    process_template<float>(3.14f); // Line 41
}

// Multiple calls in single statement
void chained_calls() {
    callback_func();  // Line 46
    external_func();  // Line 47
}
