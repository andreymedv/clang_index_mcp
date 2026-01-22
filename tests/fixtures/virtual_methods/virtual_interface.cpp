// Implementations for virtual interface test fixture
#include "virtual_interface.h"

namespace test {

void ConcreteHandler::process() {
    // Implementation
}

int ConcreteHandler::calculate(int x) const {
    return x * 2;
}

void ConcreteHandler::helperMethod() {
    // Non-virtual helper
}

void ConcreteHandler::staticHelper() {
    // Static method
}

int ConcreteHandler::getValue() const {
    return 42;
}

void SpecialHandler::process() {
    // Special implementation
}

int SpecialHandler::calculate(int x) const {
    return x * 3;
}

void SpecialHandler::onInit() {
    // Override the default
}

}  // namespace test
