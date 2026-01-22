// Test fixture for virtual method extraction (Phase 5)
#pragma once

namespace test {

// Abstract interface with pure virtual methods
class IHandler {
public:
    virtual ~IHandler() = default;

    // Pure virtual methods (no implementation allowed in this class)
    virtual void process() = 0;
    virtual int calculate(int x) const = 0;

    // Virtual method with default implementation
    virtual void onInit() {}
};

// Concrete implementation
class ConcreteHandler : public IHandler {
public:
    void process() override;
    int calculate(int x) const override;

    // Non-virtual method
    void helperMethod();

    // Static method
    static void staticHelper();

    // Const method (non-virtual)
    int getValue() const;
};

// Another implementation for testing multiple overrides
class SpecialHandler : public IHandler {
public:
    void process() override;
    int calculate(int x) const override;
    void onInit() override;
};

}  // namespace test
