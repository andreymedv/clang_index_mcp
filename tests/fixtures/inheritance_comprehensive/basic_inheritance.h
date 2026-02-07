#ifndef BASIC_INHERITANCE_H
#define BASIC_INHERITANCE_H

namespace inheritance_test {

// ============================================================================
// TEST CASE 1: Single public inheritance
// ============================================================================

struct SingleBase {
    virtual ~SingleBase() = default;
    virtual void baseMethod() {}
};

struct SingleDerived : public SingleBase {
    void derivedMethod() {}
    void baseMethod() override {}
};

// ============================================================================
// TEST CASE 2: Multiple public inheritance (2 bases)
// ============================================================================

struct MultiBaseA {
    void methodA() {}
};

struct MultiBaseB {
    void methodB() {}
};

struct MultiDerived2 : public MultiBaseA, public MultiBaseB {
    void ownMethod() {}
};

// ============================================================================
// TEST CASE 3: Multiple inheritance (3+ bases)
// ============================================================================

struct MultiBaseC {
    void methodC() {}
};

struct MultiDerived3 : public MultiBaseA, public MultiBaseB, public MultiBaseC {
    void ownMethod3() {}
};

// ============================================================================
// TEST CASE 4: Deep hierarchy (5 levels: A -> B -> C -> D -> E)
// ============================================================================

struct DeepA {
    virtual ~DeepA() = default;
    void deepMethodA() {}
};

struct DeepB : public DeepA {
    void deepMethodB() {}
};

struct DeepC : public DeepB {
    void deepMethodC() {}
};

struct DeepD : public DeepC {
    void deepMethodD() {}
};

struct DeepE : public DeepD {
    void deepMethodE() {}
};

// ============================================================================
// TEST CASE 5: Protected inheritance
// ============================================================================

struct ProtectedDerived : protected SingleBase {
    void protectedMethod() {}
};

// ============================================================================
// TEST CASE 6: Private inheritance
// ============================================================================

struct PrivateDerived : private SingleBase {
    void privateMethod() {}
};

// ============================================================================
// TEST CASE 7: Mixed access specifiers (public A, protected B, private C)
// ============================================================================

struct MixedAccessDerived : public MultiBaseA, protected MultiBaseB, private MultiBaseC {
    void mixedMethod() {}
};

// ============================================================================
// TEST CASE 8: Struct inheriting from class and vice versa
// ============================================================================

class ClassBase {
public:
    virtual ~ClassBase() = default;
    void classBaseMethod() {}
};

struct StructFromClass : public ClassBase {
    void structMethod() {}
};

class ClassFromStruct : public SingleBase {
public:
    void classMethod() {}
};

}  // namespace inheritance_test

#endif  // BASIC_INHERITANCE_H
