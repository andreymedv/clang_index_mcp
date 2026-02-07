#ifndef SPECIALIZATION_INHERITANCE_H
#define SPECIALIZATION_INHERITANCE_H

namespace inheritance_test {

// ============================================================================
// TEST CASE 42: Primary template with base A, full specialization with base B
// ============================================================================

struct SpecBaseA {
    void specBaseAMethod() {}
};

struct SpecBaseB {
    void specBaseBMethod() {}
};

template <typename T>
class SpecPrimary : public SpecBaseA {
public:
    void primaryMethod() {}
    T getValue() { return T{}; }
};

template <>
class SpecPrimary<int> : public SpecBaseB {
public:
    void primaryMethod() {}
    int getValue() { return 0; }
    void intSpecificMethod() {}
};

// ============================================================================
// TEST CASE 43: Partial specialization with different base than primary
// ============================================================================

struct SpecBaseC {
    void specBaseCMethod() {}
};

template <typename T, typename U>
class PartialSpec : public SpecBaseA {
public:
    void partialMethod() {}
};

// Partial specialization: when T is int*, use SpecBaseC instead
template <typename U>
class PartialSpec<int*, U> : public SpecBaseC {
public:
    void partialMethod() {}
    void pointerSpecificMethod() {}
};

// ============================================================================
// TEST CASE 44: Specialization adding extra base classes
// ============================================================================

template <typename T>
class SpecExtraBases : public SpecBaseA {
public:
    void specExtraMethod() {}
};

// Full specialization adds SpecBaseB as additional base
template <>
class SpecExtraBases<double> : public SpecBaseA, public SpecBaseB {
public:
    void specExtraMethod() {}
    void doubleSpecificMethod() {}
};

// ============================================================================
// TEST CASE 45: Specialization removing base classes
// ============================================================================

template <typename T>
class SpecRemoveBases : public SpecBaseA, public SpecBaseB {
public:
    void specRemoveMethod() {}
};

// Full specialization with only SpecBaseA (removed SpecBaseB)
template <>
class SpecRemoveBases<char> : public SpecBaseA {
public:
    void specRemoveMethod() {}
    void charSpecificMethod() {}
};

// ============================================================================
// TEST CASE 46: Multiple specializations each with different inheritance
// ============================================================================

template <typename T>
class MultiSpec : public SpecBaseA {
public:
    void multiSpecMethod() {}
};

template <>
class MultiSpec<int> : public SpecBaseB {
public:
    void multiSpecMethod() {}
};

template <>
class MultiSpec<double> : public SpecBaseC {
public:
    void multiSpecMethod() {}
};

template <>
class MultiSpec<char> : public SpecBaseA, public SpecBaseB, public SpecBaseC {
public:
    void multiSpecMethod() {}
};

}  // namespace inheritance_test

#endif  // SPECIALIZATION_INHERITANCE_H
