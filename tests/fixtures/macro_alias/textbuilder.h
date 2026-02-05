// Full definition header for DataBuilder
#pragma once
#include "textbuilder_fwd.h"

namespace test {
namespace builders {

struct DataBuilder {
    int value;

    // Static factory method that returns DataBuilderUPtr
    static DataBuilderUPtr builder();
};

}  // namespace builders
}  // namespace test
