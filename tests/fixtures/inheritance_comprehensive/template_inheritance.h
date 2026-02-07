#ifndef TEMPLATE_INHERITANCE_H
#define TEMPLATE_INHERITANCE_H

namespace inheritance_test {

// ============================================================================
// TEST CASE 14: Template inheriting from single template parameter
// ============================================================================

template <typename T>
class SingleParamBase : public T {
public:
    void singleParamMethod() {}
};

// ============================================================================
// TEST CASE 15: Template inheriting from multiple template parameters
// ============================================================================

template <typename A, typename B>
class MultiParamBase : public A, public B {
public:
    void multiParamMethod() {}
};

// ============================================================================
// TEST CASE 16: Template inheriting from Nth parameter only
// ============================================================================

template <typename A, typename B>
class NthParamBase : public B {
public:
    void nthParamMethod() {}
    // A is used only as a type parameter, not as a base
    A getMember() { return A{}; }
};

// ============================================================================
// TEST CASE 17: Template with fixed + parameter bases
// ============================================================================

struct FixedBase {
    void fixedBaseMethod() {}
};

template <typename T>
class FixedPlusParam : public T, protected FixedBase {
public:
    void fixedPlusParamMethod() {}
};

// ============================================================================
// TEST CASE 18: Non-template class inheriting from template instantiation
// ============================================================================

template <typename T>
class GenericContainer {
public:
    void containerMethod() {}
    T getValue() { return T{}; }
};

struct IntContainer : public GenericContainer<int> {
    void intSpecificMethod() {}
};

struct DoubleContainer : public GenericContainer<double> {
    void doubleSpecificMethod() {}
};

// ============================================================================
// TEST CASE 19: Nested template inheritance
// ============================================================================

template <typename T>
class InnerWrapper {
public:
    void innerMethod() {}
};

template <typename T>
class OuterWrapper {
public:
    void outerMethod() {}
};

struct NestedTemplateChild : public OuterWrapper<InnerWrapper<int>> {
    void nestedMethod() {}
};

// ============================================================================
// TEST CASE 20: Template inheriting from template instantiation
// ============================================================================

template <typename T>
class TemplateFromTemplate : public GenericContainer<T> {
public:
    void templateFromTemplateMethod() {}
};

// Concrete instantiation
struct ConcreteFromTemplate : public TemplateFromTemplate<int> {
    void concreteMethod() {}
};

}  // namespace inheritance_test

#endif  // TEMPLATE_INHERITANCE_H
