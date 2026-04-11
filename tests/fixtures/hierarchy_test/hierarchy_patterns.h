/**
 * Test fixture for get_class_hierarchy BFS algorithm testing.
 * Uses abstract class names (A, BaseB, CImpl, etc.) as required.
 *
 * Patterns covered:
 * - Linear inheritance chain (A1 -> A2 -> A3 -> A4 -> A5)
 * - Multiple inheritance (MultiDerived : BaseX, BaseY, BaseZ)
 * - Virtual inheritance / diamond pattern
 * - Template inheritance with CRTP
 * - Shared base scenario (the bug being fixed)
 * - Mixed template and non-template classes
 */

#pragma once

// ============================================================================
// Pattern 1: Linear Inheritance Chain
// A1 (base) -> A2 -> A3 -> A4 -> A5 (leaf)
// ============================================================================

class A1 {
public:
    virtual ~A1() = default;
};

class A2 : public A1 {
public:
    virtual void methodA2() = 0;
};

class A3 : public A2 {
public:
    void methodA2() override {}
};

class A4 : public A3 {
public:
    virtual void methodA4() {}
};

class A5 : public A4 {
public:
    void methodA4() override {}
};

// ============================================================================
// Pattern 2: Multiple Inheritance
// ============================================================================

class BaseX {
public:
    virtual ~BaseX() = default;
    virtual void xMethod() = 0;
};

class BaseY {
public:
    virtual ~BaseY() = default;
    virtual void yMethod() = 0;
};

class BaseZ {
public:
    virtual ~BaseZ() = default;
    virtual void zMethod() = 0;
};

// MultiDerived inherits from 3 independent bases
class MultiDerived : public BaseX, public BaseY, public BaseZ {
public:
    void xMethod() override {}
    void yMethod() override {}
    void zMethod() override {}
};

// Another derived class from BaseX
class DerivedX2 : public BaseX {
public:
    void xMethod() override {}
};

// ============================================================================
// Pattern 3: Virtual Inheritance (Diamond)
//      VBase
 *     /   \
 * VLeft   VRight
 *     \   /
 *    VBottom
 * ============================================================================
 */

class VBase {
public:
    virtual ~VBase() = default;
    virtual void vbaseMethod() = 0;
};

class VLeft : virtual public VBase {
public:
    void vbaseMethod() override {}
    virtual void vleftMethod() = 0;
};

class VRight : virtual public VBase {
public:
    void vbaseMethod() override {}
    virtual void vrightMethod() = 0;
};

class VBottom : public VLeft, public VRight {
public:
    void vleftMethod() override {}
    void vrightMethod() override {}
};

// ============================================================================
// Pattern 4: CRTP (Curiously Recurring Template Pattern)
// ============================================================================

template <typename T>
class CRTPBase {
public:
    T* self() { return static_cast<T*>(this); }
    const T* self() const { return static_cast<const T*>(this); }
};

class CRTPImpl : public CRTPBase<CRTPImpl> {
public:
    void doSomething() {}
};

// Multi-level CRTP
template <typename T>
class CRTPLevel1 : public CRTPBase<T> {};

template <typename T>
class CRTPLevel2 : public CRTPLevel1<T> {};

class CRTPDeep : public CRTPLevel2<CRTPDeep> {};

// CRTP with additional mixin
template <typename Derived, typename Mixin>
class CRTPMixin : public Mixin {
public:
    Derived* self() { return static_cast<Derived*>(this); }
};

class MixinBase {
public:
    void mixinMethod() {}
};

class CRTPWithMixin : public CRTPMixin<CRTPWithMixin, MixinBase> {};

// ============================================================================
// Pattern 5: Shared Base Scenario (the bug being fixed)
//
// This simulates the real-world bug where get_class_hierarchy would return
// unrelated classes through shared intermediate bases.
//
// Before fix: Querying LeafA would return all Impl classes because:
//   LeafA -> ImplBaseA -> SharedBase
//   Then from SharedBase, ALL derived classes were returned (ImplB, ImplC, etc.)
//
// After fix: Querying LeafA should only return:
//   Ancestors: ImplBaseA, SharedBase
//   Descendants: only from LeafA itself (none in this case)
// ============================================================================

class SharedBase {
public:
    virtual ~SharedBase() = default;
    virtual void sharedMethod() = 0;
};

// First branch
class ImplBaseA : public SharedBase {
public:
    void sharedMethod() override {}
    virtual void implAMethod() = 0;
};

class LeafA : public ImplBaseA {
public:
    void implAMethod() override {}
};

// Second branch (sibling, not descendant of LeafA)
class ImplBaseB : public SharedBase {
public:
    void sharedMethod() override {}
    virtual void implBMethod() = 0;
};

class LeafB : public ImplBaseB {
public:
    void implBMethod() override {}
};

// Third branch (another sibling)
class ImplBaseC : public SharedBase {
public:
    void sharedMethod() override {}
    virtual void implCMethod() = 0;
};

class LeafC1 : public ImplBaseC {
public:
    void implCMethod() override {}
};

class LeafC2 : public ImplBaseC {
public:
    void implCMethod() override {}
};

// ============================================================================
// Pattern 6: Template Inheritance
// ============================================================================

template <typename T>
class TemplateBase {
public:
    virtual ~TemplateBase() = default;
    virtual T getValue() = 0;
};

// Non-template class deriving from template instantiation
class IntContainer : public TemplateBase<int> {
public:
    int getValue() override { return 42; }
};

class DoubleContainer : public TemplateBase<double> {
public:
    double getValue() override { return 3.14; }
};

// Template deriving from template parameter
template <typename T>
class ParamInherit : public T {
public:
    void extendedMethod() {}
};

// Template deriving from both template param and fixed base
template <typename T>
class MixedInherit : public T, public BaseX {
public:
    void xMethod() override {}
};

// Usage of ParamInherit
class ParamInheritUser : public ParamInherit<A1> {};

// ============================================================================
// Pattern 7: Namespace Ambiguity Test
// ============================================================================

namespace ns1 {
class CommonName {
public:
    virtual ~CommonName() = default;
};

class DerivedInNs1 : public CommonName {};
}  // namespace ns1

namespace ns2 {
class CommonName {
public:
    virtual ~CommonName() = default;
};

class DerivedInNs2 : public CommonName {};
}  // namespace ns2

// Qualified inheritance
class QualifiedDerived : public ns1::CommonName {};

// ============================================================================
// Pattern 8: Intermediate Class in Deep Hierarchy
// BaseI -> MiddleI1 -> MiddleI2 -> LeafI
// Used to test that intermediate classes correctly report both bases and derived
// ============================================================================

class BaseI {
public:
    virtual ~BaseI() = default;
    virtual void baseIMethod() = 0;
};

class MiddleI1 : public BaseI {
public:
    void baseIMethod() override {}
    virtual void middle1Method() = 0;
};

class MiddleI2 : public MiddleI1 {
public:
    void middle1Method() override {}
    virtual void middle2Method() = 0;
};

class LeafI : public MiddleI2 {
public:
    void middle2Method() override {}
};
