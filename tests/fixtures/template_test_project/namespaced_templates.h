#ifndef NAMESPACED_TEMPLATES_H
#define NAMESPACED_TEMPLATES_H

// ============================================================================
// TEST CASE 19: Templates in Namespaces
// ============================================================================

namespace outer {

/// Template in namespace
template<typename T>
class NamespacedContainer {
public:
    T data;
};

/// Full specialization in same namespace
template<>
class NamespacedContainer<int> {
public:
    int data;
    void optimize();
};

namespace inner {

/// Template in nested namespace
template<typename T, typename U>
class NestedPair {
public:
    T first;
    U second;
};

/// Partial specialization in nested namespace
template<typename T>
class NestedPair<T, T> {
public:
    T first;
    T second;
    bool areEqual() const { return first == second; }
};

/// Full specialization in nested namespace
template<>
class NestedPair<int, double> {
public:
    int first;
    double second;
    double sum() const { return first + second; }
};

} // namespace inner

} // namespace outer

// ============================================================================
// TEST CASE 20: Forward Declared Templates
// ============================================================================

namespace forward_decl {

// Forward declaration
template<typename T>
class ForwardDeclared;

// Full definition
template<typename T>
class ForwardDeclared {
public:
    T value;
    void process();
};

// Specialization of forward-declared template
template<>
class ForwardDeclared<void> {
public:
    void process();
};

} // namespace forward_decl

// ============================================================================
// TEST CASE 21: Cross-Namespace Inheritance
// ============================================================================

namespace base_ns {

template<typename T>
class BaseTemplate {
public:
    T data;
    virtual void process() {}
};

} // namespace base_ns

namespace derived_ns {

// Class derived from template in different namespace
class DerivedFromTemplate : public base_ns::BaseTemplate<int> {
public:
    void process() override {}
    void extraMethod();
};

} // namespace derived_ns

#endif // NAMESPACED_TEMPLATES_H
