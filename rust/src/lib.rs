use pyo3::prelude::*;

mod bindings;
mod headers;
mod multipart;

#[pymodule]
fn _core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<bindings::PyMultipartParser>()?;
    module.add_class::<bindings::PyMultipartState>()?;
    module.add_class::<bindings::PyPartBegin>()?;
    module.add_class::<bindings::PyPartData>()?;
    module.add_class::<bindings::PyPartEnd>()?;
    module.add_function(wrap_pyfunction!(headers::parse_options_header, module)?)?;
    Ok(())
}
