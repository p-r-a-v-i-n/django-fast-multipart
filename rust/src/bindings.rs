use pyo3::{prelude::*, types::PyBytes};

use crate::multipart::{MultipartEvent, MultipartParser, MultipartState};

#[pyclass(name = "MultipartState", eq, eq_int, skip_from_py_object)]
#[derive(Clone, Copy, PartialEq, Debug)]
pub enum PyMultipartState {
    #[pyo3(name = "PREAMBLE")]
    Preamble,
    #[pyo3(name = "HEADER")]
    Header,
    #[pyo3(name = "BODY")]
    Body,
    #[pyo3(name = "END")]
    End,
}

impl From<MultipartState> for PyMultipartState {
    fn from(state: MultipartState) -> Self {
        match state {
            MultipartState::Preamble => Self::Preamble,
            MultipartState::Header => Self::Header,
            MultipartState::Body => Self::Body,
            MultipartState::End => Self::End,
        }
    }
}

#[pyclass(name = "PartBegin", frozen)]
pub struct PyPartBegin {
    #[pyo3(get)]
    headers: Vec<(Py<PyBytes>, Py<PyBytes>)>,
}

#[pymethods]
impl PyPartBegin {
    fn __repr__(&self, py: Python<'_>) -> PyResult<String> {
        let headers: PyResult<Vec<String>> = self
            .headers
            .iter()
            .map(|(name, value)| {
                Ok(format!(
                    "({}, {})",
                    name.bind(py).repr()?,
                    value.bind(py).repr()?
                ))
            })
            .collect();
        Ok(format!("PartBegin(headers=[{}])", headers?.join(", ")))
    }
}

#[pyclass(name = "PartData", frozen)]
pub struct PyPartData {
    #[pyo3(get)]
    data: Py<PyBytes>,
}

#[pymethods]
impl PyPartData {
    fn __repr__(&self, py: Python<'_>) -> PyResult<String> {
        Ok(format!("PartData(data={})", self.data.bind(py).repr()?))
    }
}

#[pyclass(name = "PartEnd", frozen)]
pub struct PyPartEnd;

#[pymethods]
impl PyPartEnd {
    fn __repr__(&self) -> &'static str {
        "PartEnd()"
    }
}

fn event_to_py(py: Python<'_>, event: MultipartEvent) -> PyResult<Py<PyAny>> {
    let object = match event {
        MultipartEvent::Begin { headers } => {
            let headers = headers
                .into_iter()
                .map(|(name, value)| {
                    (
                        PyBytes::new(py, &name).unbind(),
                        PyBytes::new(py, &value).unbind(),
                    )
                })
                .collect();
            Bound::new(py, PyPartBegin { headers })?.into_any()
        }
        MultipartEvent::Data { data } => Bound::new(
            py,
            PyPartData {
                data: PyBytes::new(py, &data).unbind(),
            },
        )?
        .into_any(),
        MultipartEvent::End => Bound::new(py, PyPartEnd)?.into_any(),
    };
    Ok(object.unbind())
}

#[pyclass(name = "MultipartParser")]
pub struct PyMultipartParser {
    parser: MultipartParser,
}

#[pymethods]
impl PyMultipartParser {
    #[new]
    #[pyo3(signature = (
        boundary,
        *,
        max_size = None,
        max_header_count = 8,
        max_header_size = 4224,
        max_total_header_size = None,
    ))]
    fn new(
        boundary: Vec<u8>,
        max_size: Option<usize>,
        max_header_count: usize,
        max_header_size: usize,
        max_total_header_size: Option<usize>,
    ) -> PyResult<Self> {
        Ok(Self {
            parser: MultipartParser::new(
                boundary,
                max_size,
                max_header_count,
                max_header_size,
                max_total_header_size,
            )?,
        })
    }

    #[getter]
    fn state(&self) -> PyMultipartState {
        self.parser.state().into()
    }

    fn feed(&mut self, py: Python<'_>, data: &[u8]) -> PyResult<Vec<Py<PyAny>>> {
        self.parser
            .feed(data)?
            .into_iter()
            .map(|event| event_to_py(py, event))
            .collect()
    }

    fn feed_eof(&mut self, py: Python<'_>) -> PyResult<Vec<Py<PyAny>>> {
        self.parser
            .feed_eof()?
            .into_iter()
            .map(|event| event_to_py(py, event))
            .collect()
    }

    fn finish(&self) -> PyResult<()> {
        self.parser.finish()
    }
}
