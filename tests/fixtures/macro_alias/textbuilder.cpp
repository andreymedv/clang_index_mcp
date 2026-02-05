// Implementation file for DataBuilder
#include "textbuilder.h"

namespace test {
namespace builders {

DataBuilderUPtr DataBuilder::builder() {
    DataBuilderUPtr result;
    result.ptr = new DataBuilder();
    return result;
}

}  // namespace builders
}  // namespace test
