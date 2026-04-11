// Main file for hierarchy test fixture
// Ensures all classes are instantiated and indexed

#include "hierarchy_patterns.h"

// Instantiate template classes to ensure they are indexed
template class ParamInherit<A1>;
template class MixedInherit<A2>;

// Force instantiation of CRTP templates
template class CRTPBase<CRTPImpl>;
template class CRTPLevel1<CRTPDeep>;
template class CRTPLevel2<CRTPDeep>;
template class CRTPMixin<CRTPWithMixin, MixinBase>;

int main() {
    // Create instances to ensure classes are used
    A5 a5;
    MultiDerived multi;
    VBottom vbottom;
    CRTPImpl crtp;
    CRTPDeep crtpDeep;
    CRTPWithMixin crtpMixin;
    LeafA leafA;
    LeafB leafB;
    LeafC1 leafC1;
    LeafC2 leafC2;
    IntContainer intCont;
    DoubleContainer doubleCont;
    ParamInheritUser paramUser;
    QualifiedDerived qualDerived;
    LeafI leafI;

    // Use instances to prevent optimization
    (void)a5;
    (void)multi;
    (void)vbottom;
    (void)crtp;
    (void)crtpDeep;
    (void)crtpMixin;
    (void)leafA;
    (void)leafB;
    (void)leafC1;
    (void)leafC2;
    (void)intCont;
    (void)doubleCont;
    (void)paramUser;
    (void)qualDerived;
    (void)leafI;

    return 0;
}
