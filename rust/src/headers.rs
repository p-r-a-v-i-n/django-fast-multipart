use std::collections::HashMap;

use pyo3::{exceptions::PyValueError, prelude::*};

/// Parse a MIME-style header value and its parameters.
///
/// Quoted parameter values follow [RFC 2045 section 5.1](https://www.rfc-editor.org/rfc/rfc2045.html#section-5.1).
#[pyfunction]
pub fn parse_options_header(value: &str) -> PyResult<(String, HashMap<String, String>)> {
    let mut segments = Vec::new();
    let mut start = 0;
    let mut quoted = false;
    let mut escaped = false;

    for (index, character) in value.char_indices() {
        if escaped {
            escaped = false;
        } else if quoted && character == '\\' {
            escaped = true;
        } else if character == '"' {
            quoted = !quoted;
        } else if character == ';' && !quoted {
            segments.push(&value[start..index]);
            start = index + 1;
        }
    }
    if quoted || escaped {
        return Err(PyValueError::new_err("Malformed quoted parameter"));
    }
    segments.push(&value[start..]);

    let name = segments.remove(0).trim();
    if name.is_empty() {
        return Err(PyValueError::new_err("Missing header name"));
    }

    let mut parameters = HashMap::new();
    for segment in segments {
        let (key, raw_value) = segment
            .split_once('=')
            .ok_or_else(|| PyValueError::new_err("Missing parameter value"))?;
        let key = key.trim();
        if key.is_empty() {
            return Err(PyValueError::new_err("Missing parameter key"));
        }

        let raw_value = raw_value.trim();
        let parameter = if raw_value.starts_with('"') {
            if raw_value.len() < 2 || !raw_value.ends_with('"') {
                return Err(PyValueError::new_err("Malformed quoted parameter"));
            }
            let mut parameter = String::new();
            let mut escaped = false;
            // A trailing escape inside quotes is already rejected by the quoted/escaped scan above.
            for character in raw_value[1..raw_value.len() - 1].chars() {
                if escaped {
                    parameter.push(character);
                    escaped = false;
                } else if character == '\\' {
                    escaped = true;
                } else {
                    parameter.push(character);
                }
            }
            parameter
        } else {
            raw_value.to_string()
        };
        parameters.insert(key.to_ascii_lowercase(), parameter);
    }

    Ok((name.to_string(), parameters))
}
