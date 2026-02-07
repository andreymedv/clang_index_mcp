#ifndef CRTP_PATTERNS_H
#define CRTP_PATTERNS_H

namespace inheritance_test {

// ============================================================================
// TEST CASE 21: Basic CRTP
// ============================================================================

template <typename Derived>
class CRTPBase {
public:
    void interface() {
        static_cast<Derived*>(this)->implementation();
    }
    void crtpBaseMethod() {}
};

struct CRTPConcrete : public CRTPBase<CRTPConcrete> {
    void implementation() {}
    void concreteMethod() {}
};

// ============================================================================
// TEST CASE 22: CRTP with intermediate layer
// ============================================================================

struct CRTPMid : public CRTPBase<CRTPMid> {
    void implementation() {}
    void midMethod() {}
};

struct CRTPBottom : public CRTPMid {
    void bottomMethod() {}
};

// ============================================================================
// TEST CASE 23: CRTP with additional base classes
// ============================================================================

struct ExtraCRTPBase {
    void extraMethod() {}
};

template <typename Derived>
class CRTPWithExtra : public CRTPBase<Derived>, public ExtraCRTPBase {
public:
    void crtpExtraMethod() {}
};

struct CRTPExtraConcrete : public CRTPWithExtra<CRTPExtraConcrete> {
    void implementation() {}
    void extraConcreteMethod() {}
};

// ============================================================================
// TEST CASE 24: Multi-level CRTP chain
// ============================================================================

template <typename Derived>
class CRTPLevel1 {
public:
    void level1Method() {}
};

template <typename Derived>
class CRTPLevel2 : public CRTPLevel1<Derived> {
public:
    void level2Method() {}
};

struct CRTPChainEnd : public CRTPLevel2<CRTPChainEnd> {
    void chainEndMethod() {}
};

// ============================================================================
// TEST CASE 25: CRTP with pure virtual interface methods
// ============================================================================

template <typename Derived>
class CRTPPureInterface {
public:
    virtual ~CRTPPureInterface() = default;
    void doWork() {
        static_cast<Derived*>(this)->doWorkImpl();
    }
};

struct CRTPPureConcrete : public CRTPPureInterface<CRTPPureConcrete> {
    void doWorkImpl() {}
};

}  // namespace inheritance_test

#endif  // CRTP_PATTERNS_H
