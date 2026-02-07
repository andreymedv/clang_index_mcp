#ifndef MIXIN_PATTERNS_H
#define MIXIN_PATTERNS_H

namespace inheritance_test {

// ============================================================================
// TEST CASE 26: Single mixin
// ============================================================================

struct MixinTarget {
    void targetMethod() {}
};

template <typename Base>
class LoggingMixin : public Base {
public:
    void log() {}
};

struct LoggedTarget : public LoggingMixin<MixinTarget> {
    void loggedMethod() {}
};

// ============================================================================
// TEST CASE 27: Mixin chain stacking 3+ mixins
// ============================================================================

template <typename Base>
class SerializableMixin : public Base {
public:
    void serialize() {}
};

template <typename Base>
class CloneableMixin : public Base {
public:
    void clone() {}
};

// Stacked: Logging<Serializable<Cloneable<MixinTarget>>>
struct FullyMixedTarget
    : public LoggingMixin<SerializableMixin<CloneableMixin<MixinTarget>>> {
    void fullMethod() {}
};

// ============================================================================
// TEST CASE 28: Policy-based design (multiple template params as behaviors)
// ============================================================================

struct DefaultCreationPolicy {
    void create() {}
};

struct DefaultLifetimePolicy {
    void destroy() {}
};

template <typename CreationPolicy, typename LifetimePolicy>
class PolicyHost : public CreationPolicy, public LifetimePolicy {
public:
    void hostMethod() {}
};

struct CustomCreation {
    void create() {}
};

struct CustomLifetime {
    void destroy() {}
};

struct DefaultPolicyHost
    : public PolicyHost<DefaultCreationPolicy, DefaultLifetimePolicy> {
    void defaultHostMethod() {}
};

struct CustomPolicyHost
    : public PolicyHost<CustomCreation, CustomLifetime> {
    void customHostMethod() {}
};

// ============================================================================
// TEST CASE 29: Mixin with additional fixed base
// ============================================================================

struct FixedMixinBase {
    void fixedMixinMethod() {}
};

template <typename Base>
class MixinWithFixed : public Base, public FixedMixinBase {
public:
    void mixinFixedMethod() {}
};

struct MixinFixedTarget : public MixinWithFixed<MixinTarget> {
    void mixinFixedTargetMethod() {}
};

// ============================================================================
// TEST CASE 30: Mixin with CRTP combination
// ============================================================================

template <typename Derived, typename Base>
class CRTPMixin : public Base {
public:
    void crtpMixinMethod() {
        static_cast<Derived*>(this)->crtpMixinImpl();
    }
};

struct CRTPMixinConcrete
    : public CRTPMixin<CRTPMixinConcrete, MixinTarget> {
    void crtpMixinImpl() {}
};

}  // namespace inheritance_test

#endif  // MIXIN_PATTERNS_H
