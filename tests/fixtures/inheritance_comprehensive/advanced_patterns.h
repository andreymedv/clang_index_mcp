#ifndef ADVANCED_PATTERNS_H
#define ADVANCED_PATTERNS_H

namespace inheritance_test {

// ============================================================================
// TEST CASE 60: Variadic template inheritance
// ============================================================================

struct VariadicBaseA {
    void variadicAMethod() {}
};

struct VariadicBaseB {
    void variadicBMethod() {}
};

struct VariadicBaseC {
    void variadicCMethod() {}
};

template <typename... Bases>
class VariadicInherit : public Bases... {
public:
    void variadicMethod() {}
};

struct VariadicConcrete
    : public VariadicInherit<VariadicBaseA, VariadicBaseB, VariadicBaseC> {
    void variadicConcreteMethod() {}
};

// ============================================================================
// TEST CASE 61: Nested class inheriting from outer class's base
// ============================================================================

struct OuterBase {
    void outerBaseMethod() {}
};

struct OuterClass : public OuterBase {
    void outerClassMethod() {}

    struct InnerClass : public OuterBase {
        void innerClassMethod() {}
    };
};

// ============================================================================
// TEST CASE 62: Template with default parameter used as base
// ============================================================================

struct DefaultTemplateBase {
    void defaultTemplateBaseMethod() {}
};

template <typename T = DefaultTemplateBase>
class DefaultParamInherit : public T {
public:
    void defaultParamMethod() {}
};

// Uses default: inherits from DefaultTemplateBase
struct UsesDefault : public DefaultParamInherit<> {
    void usesDefaultMethod() {}
};

// Overrides default: inherits from VariadicBaseA
struct OverridesDefault : public DefaultParamInherit<VariadicBaseA> {
    void overridesDefaultMethod() {}
};

// ============================================================================
// TEST CASE 63: Dependent base class with typename keyword
// ============================================================================

struct TraitsHost {
    using BaseType = OuterBase;
};

template <typename Traits>
class DependentBaseDerived : public Traits::BaseType {
public:
    void dependentMethod() {}
};

// ============================================================================
// TEST CASE 64: Same name, different template args in different scopes
// ============================================================================

template <typename T>
class ScopedTemplate {
public:
    void scopedMethod() {}
};

struct FromScopedInt : public ScopedTemplate<int> {
    void fromScopedIntMethod() {}
};

struct FromScopedDouble : public ScopedTemplate<double> {
    void fromScopedDoubleMethod() {}
};

// ============================================================================
// TEST CASE 65: Template inheriting from dependent nested type
// ============================================================================

struct NestedTypeHost {
    struct Inner {
        void innerMethod() {}
    };
};

template <typename T>
class InheritsNestedType : public T::Inner {
public:
    void inheritsNestedMethod() {}
};

struct ConcreteNestedInherit : public InheritsNestedType<NestedTypeHost> {
    void concreteNestedMethod() {}
};

}  // namespace inheritance_test

#endif  // ADVANCED_PATTERNS_H
