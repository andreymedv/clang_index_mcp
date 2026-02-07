#ifndef ALIAS_INHERITANCE_H
#define ALIAS_INHERITANCE_H

namespace inheritance_test {

// ============================================================================
// TEST CASE 54: Simple type alias used as base class
// ============================================================================

struct ConcreteAliasBase {
    void concreteAliasMethod() {}
};

using AliasBase = ConcreteAliasBase;

struct DerivedFromAlias : public AliasBase {
    void derivedFromAliasMethod() {}
};

// ============================================================================
// TEST CASE 55: Template alias (not directly inheritable, but tests tracking)
// ============================================================================

template <typename T>
class TemplateAliasTarget {
public:
    void templateAliasTargetMethod() {}
};

template <typename T>
using TemplateAlias = TemplateAliasTarget<T>;

// Cannot inherit from alias template directly, but can inherit from instantiation
struct DerivedFromTemplateAlias : public TemplateAlias<int> {
    void derivedFromTemplateAliasMethod() {}
};

// ============================================================================
// TEST CASE 56: Alias to template instantiation used as base
// ============================================================================

template <typename T>
class GenericStore {
public:
    void storeMethod() {}
};

using IntStore = GenericStore<int>;

struct DerivedFromIntStore : public IntStore {
    void derivedFromIntStoreMethod() {}
};

// ============================================================================
// TEST CASE 57: Alias in one namespace to a class in another, then inheritance
// ============================================================================

namespace alias_source {
struct OriginalClass {
    void originalMethod() {}
};
}  // namespace alias_source

namespace alias_target {
using AliasToOriginal = alias_source::OriginalClass;

struct DerivedFromCrossNsAlias : public AliasToOriginal {
    void derivedCrossNsMethod() {}
};
}  // namespace alias_target

// ============================================================================
// TEST CASE 58: Chain of aliases
// ============================================================================

struct ChainBase {
    void chainBaseMethod() {}
};

using ChainAlias1 = ChainBase;
using ChainAlias2 = ChainAlias1;
using ChainAlias3 = ChainAlias2;

struct DerivedFromChainAlias : public ChainAlias3 {
    void derivedChainMethod() {}
};

// ============================================================================
// TEST CASE 59: Template alias resolving to a class template with policy
// ============================================================================

struct DefaultPolicy {
    void policyMethod() {}
};

template <typename T, typename Policy>
class PolicyWrapper {
public:
    void policyWrapperMethod() {}
};

template <typename T>
using DefaultPolicyWrapper = PolicyWrapper<T, DefaultPolicy>;

struct DerivedFromPolicyAlias : public DefaultPolicyWrapper<int> {
    void derivedPolicyAliasMethod() {}
};

}  // namespace inheritance_test

#endif  // ALIAS_INHERITANCE_H
