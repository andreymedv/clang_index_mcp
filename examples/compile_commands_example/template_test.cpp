#include <memory>
#include <vector>

// Simple alias
class Widget {};
using WidgetAlias = Widget;

// Template aliases
template<typename T>
using Ptr = std::shared_ptr<T>;

template<typename T>
using Vec = std::vector<T>;

template<typename K, typename V>
using Map = std::map<K, V>;
