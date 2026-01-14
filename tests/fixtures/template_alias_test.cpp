// Test file for template alias detection (Phase 2.0)
// Tests libclang TYPE_ALIAS_TEMPLATE_DECL cursor kind

#include <array>
#include <functional>
#include <map>
#include <memory>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

// ============================================================================
// Test Case 1: Simple template alias (single type parameter)
// ============================================================================
template<typename T>
using Ptr = std::shared_ptr<T>;

// ============================================================================
// Test Case 2: Multiple type parameters
// ============================================================================
template<typename T, typename U>
using Pair = std::pair<T, U>;

// ============================================================================
// Test Case 3: Non-type parameter
// ============================================================================
template<typename T, int N>
using Array = std::array<T, N>;

// ============================================================================
// Test Case 4: Variadic template parameters
// ============================================================================
template<typename... Args>
using Tuple = std::tuple<Args...>;

// ============================================================================
// Test Case 5: Template alias with default parameter
// ============================================================================
template<typename T, typename Alloc = std::allocator<T>>
using Vector = std::vector<T, Alloc>;

// ============================================================================
// Test Case 6: Namespace-scoped template alias
// ============================================================================
namespace utils {
    template<typename T>
    using UniquePtr = std::unique_ptr<T>;

    template<typename K, typename V>
    using Map = std::map<K, V>;
}

// ============================================================================
// Test Case 7: Nested namespace template alias
// ============================================================================
namespace outer {
    namespace inner {
        template<typename T>
        using SmartPtr = std::shared_ptr<T>;
    }
}

// ============================================================================
// Test Case 8: Template alias using function type
// ============================================================================
template<typename R, typename... Args>
using Function = std::function<R(Args...)>;

// ============================================================================
// Test Case 9: Template alias with const/reference modifiers
// ============================================================================
template<typename T>
using ConstPtr = const T*;

template<typename T>
using Ref = T&;

// ============================================================================
// Test Case 10: Complex nested template
// ============================================================================
template<typename T>
using VectorOfPairs = std::vector<std::pair<T, T>>;

// ============================================================================
// Test Case 11: Multiple non-type parameters
// ============================================================================
template<typename T, int Rows, int Cols>
using Matrix = std::array<std::array<T, Cols>, Rows>;

// ============================================================================
// Test Case 12: Template alias chain (template → simple)
// ============================================================================
template<typename T>
using SharedPtr = std::shared_ptr<T>;

// Create a simple alias from template (instantiation, not template itself)
using IntPtr = SharedPtr<int>;

// ============================================================================
// Test functions using template aliases (for validation)
// ============================================================================
void processPtr(Ptr<int> p) {}
void processPair(Pair<int, double> p) {}
void processArray(Array<float, 10> a) {}
void processTuple(Tuple<int, double, std::string> t) {}
void processVector(Vector<int> v) {}
void processUniquePtr(utils::UniquePtr<int> p) {}
void processFunction(Function<void, int, std::string> f) {}

// ============================================================================
// Template aliases at class scope (not directly supported, but test parsing)
// ============================================================================
class Container {
public:
    // Note: Member template aliases are not allowed in C++11/14
    // This tests that we handle them gracefully if present
};
