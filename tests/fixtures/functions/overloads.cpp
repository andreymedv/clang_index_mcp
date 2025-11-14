#include <string>

// Function overloads with different signatures
void overloadedFunc(int x) {
    // Process int
}

void overloadedFunc(double x) {
    // Process double
}

void overloadedFunc(const std::string& str) {
    // Process string
}

void overloadedFunc(int x, int y) {
    // Process two ints
}
