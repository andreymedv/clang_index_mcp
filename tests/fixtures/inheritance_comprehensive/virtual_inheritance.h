#ifndef VIRTUAL_INHERITANCE_H
#define VIRTUAL_INHERITANCE_H

namespace inheritance_test {

// ============================================================================
// TEST CASE 9: Diamond inheritance WITHOUT virtual bases (ambiguous)
// ============================================================================

struct DiamondTop {
    virtual ~DiamondTop() = default;
    void topMethod() {}
};

struct DiamondLeftNV : public DiamondTop {
    void leftMethod() {}
};

struct DiamondRightNV : public DiamondTop {
    void rightMethod() {}
};

// Note: DiamondTop is duplicated (ambiguous access without virtual)
struct DiamondBottomNV : public DiamondLeftNV, public DiamondRightNV {
    void bottomMethod() {}
};

// ============================================================================
// TEST CASE 10: Diamond inheritance WITH virtual bases (resolved)
// ============================================================================

struct DiamondLeftV : virtual public DiamondTop {
    void leftVMethod() {}
};

struct DiamondRightV : virtual public DiamondTop {
    void rightVMethod() {}
};

struct DiamondBottomV : public DiamondLeftV, public DiamondRightV {
    void bottomVMethod() {}
};

// ============================================================================
// TEST CASE 11: Mixed virtual + non-virtual bases
// ============================================================================

struct MixedVBase {
    void mixedVBaseMethod() {}
};

struct MixedNVBase {
    void mixedNVBaseMethod() {}
};

struct MixedVDerived : virtual public MixedVBase, public MixedNVBase {
    void mixedDerivedMethod() {}
};

// ============================================================================
// TEST CASE 12: Deep diamond (multi-level virtual inheritance)
// ============================================================================

struct DeepDiamondRoot {
    virtual ~DeepDiamondRoot() = default;
    void rootMethod() {}
};

struct DeepDiamondMidA : virtual public DeepDiamondRoot {
    void midAMethod() {}
};

struct DeepDiamondMidB : virtual public DeepDiamondRoot {
    void midBMethod() {}
};

struct DeepDiamondLeafA : public DeepDiamondMidA {
    void leafAMethod() {}
};

struct DeepDiamondLeafB : public DeepDiamondMidB {
    void leafBMethod() {}
};

struct DeepDiamondBottom : public DeepDiamondLeafA, public DeepDiamondLeafB {
    void bottomDeepMethod() {}
};

// ============================================================================
// TEST CASE 13: Virtual inheritance with method overrides at each level
// ============================================================================

struct VOverrideBase {
    virtual ~VOverrideBase() = default;
    virtual void action() {}
};

struct VOverrideLeft : virtual public VOverrideBase {
    void action() override {}
};

struct VOverrideRight : virtual public VOverrideBase {
    // Does NOT override action()
    void rightAction() {}
};

struct VOverrideBottom : public VOverrideLeft, public VOverrideRight {
    // Left's override is used (most derived overrider)
    void bottomAction() {}
};

}  // namespace inheritance_test

#endif  // VIRTUAL_INHERITANCE_H
