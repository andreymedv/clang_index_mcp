// Test file for libclang alias detection investigation
// Phase 1.1 of Type Alias Tracking feature

#include <functional>
#include <memory>
#include <vector>
#include <map>
#include <string>

// ============================================================================
// Test Case 1: Simple class alias (using)
// ============================================================================
class Widget {};
using WidgetAlias = Widget;

// ============================================================================
// Test Case 2: Simple class alias (typedef)
// ============================================================================
class Button {};
typedef Button ButtonAlias;

// ============================================================================
// Test Case 3: Pointer type alias
// ============================================================================
class Data {};
using DataPtr = Data*;
typedef Data* DataPointer;

// ============================================================================
// Test Case 4: Reference type alias
// ============================================================================
using DataRef = Data&;
typedef Data& DataReference;

// ============================================================================
// Test Case 5: Built-in type alias
// ============================================================================
using size_type = unsigned long;
typedef int int32_t;

// ============================================================================
// Test Case 6: STL type alias
// ============================================================================
using ErrorCallback = std::function<void(int)>;
using StringVector = std::vector<std::string>;
using StringMap = std::map<std::string, int>;

// ============================================================================
// Test Case 7: Alias chain (A -> B -> C)
// ============================================================================
class RealClass {};
using AliasOne = RealClass;
using AliasTwo = AliasOne;

// ============================================================================
// Test Case 8: Namespace-scoped alias
// ============================================================================
namespace foo {
    class LocalClass {};
    using LocalAlias = LocalClass;
}

namespace bar {
    using ExternalAlias = foo::LocalClass;
}

// ============================================================================
// Test Case 9: Enum alias
// ============================================================================
enum class Color { Red, Green, Blue };
using Colour = Color;

// ============================================================================
// Test Case 10: Struct alias
// ============================================================================
struct Point { int x; int y; };
using Position = Point;

// ============================================================================
// Test Case 11: const qualified alias
// ============================================================================
using ConstDataPtr = const Data*;

// ============================================================================
// Test Case 12: Complex nested type
// ============================================================================
using ComplexType = std::shared_ptr<std::vector<std::string>>;

// ============================================================================
// Test functions using aliases (for validation)
// ============================================================================
void processWidget(WidgetAlias w) {}
void handleButton(ButtonAlias b) {}
void useDataPtr(DataPtr p) {}
void callbackFunc(ErrorCallback cb) {}
void chainedAlias(AliasTwo obj) {}
void namespaceAlias(bar::ExternalAlias obj) {}
