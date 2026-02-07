#include "basic_inheritance.h"
#include "virtual_inheritance.h"
#include "template_inheritance.h"
#include "crtp_patterns.h"
#include "mixin_patterns.h"
#include "name_collision.h"
#include "forward_decl_inheritance.h"
#include "extern_template.h"
#include "specialization_inheritance.h"
#include "namespace_ambiguity.h"
#include "alias_inheritance.h"
#include "advanced_patterns.h"

using namespace inheritance_test;

// Force instantiation of all templates to ensure libclang sees them
void force_instantiation() {
    // basic_inheritance.h
    SingleDerived sd;
    MultiDerived2 md2;
    MultiDerived3 md3;
    DeepE de;
    ProtectedDerived pd;
    PrivateDerived pvd;
    MixedAccessDerived mad;
    StructFromClass sfc;
    ClassFromStruct cfs;

    // virtual_inheritance.h
    DiamondBottomNV dbnv;
    DiamondBottomV dbv;
    MixedVDerived mvd;
    DeepDiamondBottom ddb;
    VOverrideBottom vob;

    // template_inheritance.h
    SingleParamBase<SingleBase> spb;
    MultiParamBase<MultiBaseA, MultiBaseB> mpb;
    NthParamBase<int, SingleBase> npb;
    FixedPlusParam<SingleBase> fpp;
    IntContainer ic;
    DoubleContainer dc;
    NestedTemplateChild ntc;
    TemplateFromTemplate<int> tft;
    ConcreteFromTemplate cft;

    // crtp_patterns.h
    CRTPConcrete cc;
    CRTPBottom cb;
    CRTPExtraConcrete cec;
    CRTPChainEnd cce;
    CRTPPureConcrete cpc;

    // mixin_patterns.h
    LoggedTarget lt;
    FullyMixedTarget fmt;
    DefaultPolicyHost dph;
    CustomPolicyHost cph;
    MixinFixedTarget mft;
    CRTPMixinConcrete cmc;

    // name_collision.h
    RealDerivedFromBase rdfb;
    InstantiatedWrapper iw;
    WrapperCollidesWithBase<Base> wcb;
    HandlerWrapper<Handler> hw;
    ProcessorWrapper<Processor> pw;
    WidgetAdapter<other::Widget> wa;
    ConcreteWidgetChild cwc;
    Outer::Inner<Base> oi;

    // forward_decl_inheritance.h
    FwdDerived fd;
    MultiFwdDerived mfd;

    // extern_template.h (instantiation definitions in the header)
    ExternParamInherit<ExternBase> epi;
    ExternParamInherit<ExternBase2> epi2;
    ExternParamInherit<ExternBase3> epi3;
    ExternFixedInherit<int> efi;
    ExternFixedInherit<double> efid;
    ExternMixedInherit<ExternBase> emi;

    // specialization_inheritance.h
    SpecPrimary<float> spf;
    SpecPrimary<int> spi;
    PartialSpec<double, int> psdi;
    PartialSpec<int*, int> pspi;
    SpecExtraBases<float> sef;
    SpecExtraBases<double> sed;
    SpecRemoveBases<int> sri;
    SpecRemoveBases<char> src;
    MultiSpec<float> msf;
    MultiSpec<int> msi;
    MultiSpec<double> msd;
    MultiSpec<char> msc;

    // namespace_ambiguity.h
    gui::Button gb;
    data::DataView ddv;
    InheritsFromNs1 ifn1;
    InheritsFromNs2 ifn2;
    target_ns::InheritsImported ii;
    DerivedFromAB dfab;
    DerivedFromCD dfcd;
    WrappedGuiWidget wgw;
    WrappedDataWidget wdw;
    ambig::UnqualDerived aud;
    QualDerived qd;

    // alias_inheritance.h
    DerivedFromAlias dfa;
    DerivedFromTemplateAlias dfta;
    DerivedFromIntStore dfis;
    alias_target::DerivedFromCrossNsAlias dfcna;
    DerivedFromChainAlias dfca;
    DerivedFromPolicyAlias dfpa;

    // advanced_patterns.h
    VariadicConcrete vc;
    OuterClass::InnerClass oic;
    UsesDefault ud;
    OverridesDefault od;
    DependentBaseDerived<TraitsHost> dbd;
    FromScopedInt fsi;
    FromScopedDouble fsd;
    ConcreteNestedInherit cni;

    // Suppress unused variable warnings
    (void)sd; (void)md2; (void)md3; (void)de; (void)pd; (void)pvd;
    (void)mad; (void)sfc; (void)cfs; (void)dbnv; (void)dbv; (void)mvd;
    (void)ddb; (void)vob; (void)spb; (void)mpb; (void)npb; (void)fpp;
    (void)ic; (void)dc; (void)ntc; (void)tft; (void)cft; (void)cc;
    (void)cb; (void)cec; (void)cce; (void)cpc; (void)lt; (void)fmt;
    (void)dph; (void)cph; (void)mft; (void)cmc; (void)rdfb; (void)iw;
    (void)wcb; (void)hw; (void)pw; (void)wa; (void)cwc; (void)oi;
    (void)fd; (void)mfd; (void)epi; (void)epi2; (void)epi3; (void)efi;
    (void)efid; (void)emi; (void)spf; (void)spi; (void)psdi; (void)pspi;
    (void)sef; (void)sed; (void)sri; (void)src; (void)msf; (void)msi;
    (void)msd; (void)msc; (void)gb; (void)ddv; (void)ifn1; (void)ifn2;
    (void)ii; (void)dfab; (void)dfcd; (void)wgw; (void)wdw; (void)aud;
    (void)qd; (void)dfa; (void)dfta; (void)dfis; (void)dfcna; (void)dfca;
    (void)dfpa; (void)vc; (void)oic; (void)ud; (void)od; (void)dbd;
    (void)fsi; (void)fsd; (void)cni;
}

int main() {
    force_instantiation();
    return 0;
}
