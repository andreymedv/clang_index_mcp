#ifndef EXTERN_TEMPLATE_H
#define EXTERN_TEMPLATE_H

namespace inheritance_test {

// ============================================================================
// TEST CASE 38: Extern template class with template param base
// ============================================================================

struct ExternBase {
    void externBaseMethod() {}
};

template <typename T>
class ExternParamInherit : public T {
public:
    void externParamMethod() {}
};

// Explicit instantiation declaration (extern = defined elsewhere)
extern template class ExternParamInherit<ExternBase>;

// ============================================================================
// TEST CASE 39: Multiple extern template instantiations of same template
// ============================================================================

struct ExternBase2 {
    void externBase2Method() {}
};

struct ExternBase3 {
    void externBase3Method() {}
};

extern template class ExternParamInherit<ExternBase2>;
extern template class ExternParamInherit<ExternBase3>;

// ============================================================================
// TEST CASE 40: Extern template where base is a fixed class (not param)
// ============================================================================

struct ExternFixedBase {
    void externFixedMethod() {}
};

template <typename T>
class ExternFixedInherit : public ExternFixedBase {
public:
    void externFixedInheritMethod() {}
    T getValue() { return T{}; }
};

extern template class ExternFixedInherit<int>;
extern template class ExternFixedInherit<double>;

// ============================================================================
// TEST CASE 41: Extern template with both fixed and param bases
// ============================================================================

struct ExternMixedFixed {
    void externMixedFixedMethod() {}
};

template <typename T>
class ExternMixedInherit : public T, public ExternMixedFixed {
public:
    void externMixedMethod() {}
};

extern template class ExternMixedInherit<ExternBase>;

}  // namespace inheritance_test

// Explicit instantiation definitions (provide the actual instantiation)
template class inheritance_test::ExternParamInherit<inheritance_test::ExternBase>;
template class inheritance_test::ExternParamInherit<inheritance_test::ExternBase2>;
template class inheritance_test::ExternParamInherit<inheritance_test::ExternBase3>;
template class inheritance_test::ExternFixedInherit<int>;
template class inheritance_test::ExternFixedInherit<double>;
template class inheritance_test::ExternMixedInherit<inheritance_test::ExternBase>;

#endif  // EXTERN_TEMPLATE_H
