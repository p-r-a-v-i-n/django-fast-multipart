//! Sans-IO parser for [RFC 7578](https://www.rfc-editor.org/rfc/rfc7578.html) `multipart/form-data`.
//!
//! The parser transitions from the preamble to part headers, then to the part body. A body can start another part or
//! finish the multipart message. Each `feed()` call returns the batch of events produced by that input. The parser
//! never accumulates part bodies: callers own storage, limits, and decoding.

use memchr::memmem;
use pyo3::{
    exceptions::{PyRuntimeError, PyValueError},
    prelude::*,
};

const CRLF: &[u8] = b"\r\n";

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum MultipartState {
    Preamble,
    Header,
    Body,
    End,
}

#[derive(Debug, Clone)]
pub enum MultipartEvent {
    Begin { headers: Vec<(Vec<u8>, Vec<u8>)> },
    Data { data: Vec<u8> },
    End,
}

#[derive(Debug, PartialEq)]
enum DelimiterSuffix {
    Open(usize),
    Close,
    Incomplete,
    Invalid,
    BareLineFeed,
}

pub struct MultipartParser {
    max_size: Option<usize>,
    max_header_count: usize,
    max_header_size: usize,
    max_total_header_size: Option<usize>,
    state: MultipartState,
    buffer: Vec<u8>,
    dash_boundary: Vec<u8>,
    delimiter_length: usize,
    // Boxed: the x86_64 SIMD searcher is over-aligned beyond what Python's object allocator guarantees.
    dash_boundary_finder: Box<memmem::Finder<'static>>,
    delimiter_finder: Box<memmem::Finder<'static>>,
    size: usize,
    current_headers: Vec<(Vec<u8>, Vec<u8>)>,
    current_total_header_size: usize,
    eof_received: bool,
}

impl MultipartParser {
    pub fn new(
        boundary: Vec<u8>,
        max_size: Option<usize>,
        max_header_count: usize,
        max_header_size: usize,
        max_total_header_size: Option<usize>,
    ) -> PyResult<Self> {
        // RFC 2046 section 5.1.1 limits boundary values to 70 characters.
        if boundary.is_empty() || boundary.len() > 70 {
            return Err(PyValueError::new_err(
                "Boundary length must be between 1 and 70 characters.",
            ));
        }

        let dash_boundary = [b"--".as_slice(), &boundary].concat();
        let delimiter = [CRLF, dash_boundary.as_slice()].concat();
        let dash_boundary_finder = Box::new(memmem::Finder::new(&dash_boundary).into_owned());
        let delimiter_finder = Box::new(memmem::Finder::new(&delimiter).into_owned());
        Ok(Self {
            max_size,
            max_header_count,
            max_header_size,
            max_total_header_size,
            state: MultipartState::Preamble,
            buffer: Vec::new(),
            dash_boundary,
            delimiter_length: delimiter.len(),
            dash_boundary_finder,
            delimiter_finder,
            size: 0,
            current_headers: Vec::new(),
            current_total_header_size: 0,
            eof_received: false,
        })
    }

    pub fn state(&self) -> MultipartState {
        self.state
    }

    pub fn feed(&mut self, data: &[u8]) -> PyResult<Vec<MultipartEvent>> {
        let mut events = Vec::new();
        if self.eof_received {
            return Err(PyValueError::new_err("Cannot feed data after EOF."));
        }
        if self.state == MultipartState::End {
            return Ok(events);
        }
        if self
            .max_size
            .is_some_and(|max_size| self.size.saturating_add(data.len()) > max_size)
        {
            return Err(PyRuntimeError::new_err("Data exceeds maximum size."));
        }
        self.size += data.len();
        self.buffer.extend_from_slice(data);

        loop {
            let progressed = match self.state {
                MultipartState::Preamble => self.handle_preamble()?,
                MultipartState::Header => self.handle_header(&mut events)?,
                MultipartState::Body => self.handle_body(&mut events)?,
                MultipartState::End => false,
            };
            if !progressed {
                return Ok(events);
            }
        }
    }

    pub fn feed_eof(&mut self) -> PyResult<Vec<MultipartEvent>> {
        if self.eof_received {
            return Ok(Vec::new());
        }
        self.eof_received = true;
        self.check_eof_header_size()?;
        self.current_headers.clear();
        let data = std::mem::take(&mut self.buffer);
        if self.state == MultipartState::Body && !data.is_empty() {
            return Ok(vec![MultipartEvent::Data { data }]);
        }
        Ok(Vec::new())
    }

    pub fn finish(&self) -> PyResult<()> {
        if self.state != MultipartState::End {
            return Err(PyValueError::new_err(
                "Incomplete multipart message: closing boundary not received.",
            ));
        }
        Ok(())
    }

    fn handle_preamble(&mut self) -> PyResult<bool> {
        // RFC 2046 section 5.1.1 requires recipients to ignore text before the first boundary delimiter.
        let mut search_from = 0;
        while let Some(relative_index) = self.dash_boundary_finder.find(&self.buffer[search_from..])
        {
            let index = search_from + relative_index;
            let starts_line = index == 0 || (index >= 2 && self.buffer[index - 2..index] == *CRLF);
            if !starts_line {
                search_from = index + 1;
                continue;
            }

            let after_boundary = index + self.dash_boundary.len();
            match delimiter_suffix(&self.buffer, after_boundary) {
                DelimiterSuffix::Open(consumed) => {
                    self.current_total_header_size = consumed - after_boundary;
                    self.buffer.drain(..consumed);
                    self.state = MultipartState::Header;
                    return Ok(true);
                }
                DelimiterSuffix::Close => {
                    self.buffer.clear();
                    self.state = MultipartState::End;
                    return Ok(true);
                }
                DelimiterSuffix::Incomplete => {
                    self.check_incomplete_header_prefix(after_boundary)?;
                    self.buffer.drain(..index);
                    return Ok(false);
                }
                DelimiterSuffix::Invalid => search_from = index + 1,
                DelimiterSuffix::BareLineFeed => {
                    return Err(PyValueError::new_err("Invalid line break after delimiter"));
                }
            }
        }

        let retained = self.dash_boundary.len() + 1;
        if self.buffer.len() > retained {
            self.buffer.drain(..self.buffer.len() - retained);
        }
        Ok(false)
    }

    fn handle_header(&mut self, events: &mut Vec<MultipartEvent>) -> PyResult<bool> {
        if let Some(index) = memmem::find(&self.buffer, CRLF) {
            if index == 0 {
                self.check_total_header_size(CRLF.len())?;
                self.buffer.drain(..CRLF.len());
                events.push(MultipartEvent::Begin {
                    headers: std::mem::take(&mut self.current_headers),
                });
                self.current_total_header_size = 0;
                self.state = MultipartState::Body;
                return Ok(true);
            }
            if index > self.max_header_size {
                return Err(PyRuntimeError::new_err("Header line exceeds maximum size."));
            }
            if self.current_headers.len() == self.max_header_count {
                return Err(PyRuntimeError::new_err(
                    "Part exceeds maximum header count.",
                ));
            }
            self.check_total_header_size(index + CRLF.len())?;
            let line = &self.buffer[..index];
            if memchr::memchr2(b'\r', b'\n', line).is_some() {
                return Err(PyValueError::new_err("Invalid line break in header"));
            }
            let separator = memchr::memchr(b':', line)
                .ok_or_else(|| PyValueError::new_err("Malformed header"))?;
            let name = line[..separator].trim_ascii();
            if name.is_empty() {
                return Err(PyValueError::new_err("Missing header name"));
            }
            let value = line[separator + 1..].trim_ascii();
            self.current_headers.push((name.to_vec(), value.to_vec()));
            self.current_total_header_size = self
                .current_total_header_size
                .saturating_add(index + CRLF.len());
            self.buffer.drain(..index + CRLF.len());
            return Ok(true);
        }
        if self.buffer.contains(&b'\n') {
            return Err(PyValueError::new_err("Invalid line break in header"));
        }
        // Tolerate one buffered `\r` so a line of exactly `max_header_size` bytes survives a CRLF split across chunks.
        let pending = self.buffer.len() - usize::from(self.buffer.ends_with(b"\r"));
        if pending > self.max_header_size {
            return Err(PyRuntimeError::new_err("Header line exceeds maximum size."));
        }
        self.check_total_header_size(self.buffer.len())?;
        Ok(false)
    }

    fn check_total_header_size(&self, additional_size: usize) -> PyResult<()> {
        if self.max_total_header_size.is_some_and(|max_size| {
            self.current_total_header_size
                .saturating_add(additional_size)
                > max_size
        }) {
            return Err(PyRuntimeError::new_err(
                "Part exceeds maximum total header size.",
            ));
        }
        Ok(())
    }

    fn check_incomplete_header_prefix(&self, after_boundary: usize) -> PyResult<()> {
        let suffix = &self.buffer[after_boundary..];
        if !suffix.starts_with(b"-") {
            self.check_total_header_size(suffix.len())?;
        }
        Ok(())
    }

    fn check_eof_header_size(&self) -> PyResult<()> {
        let Some(max_size) = self.max_total_header_size else {
            return Ok(());
        };
        let total_header_size = match self.state {
            MultipartState::Header => Some(
                self.current_total_header_size
                    .saturating_add(self.buffer.len()),
            ),
            MultipartState::Preamble if self.buffer.starts_with(&self.dash_boundary) => {
                self.incomplete_header_prefix_size(self.dash_boundary.len())
            }
            MultipartState::Body
                if self.buffer.starts_with(CRLF)
                    && self.buffer[CRLF.len()..].starts_with(&self.dash_boundary) =>
            {
                self.incomplete_header_prefix_size(self.delimiter_length)
            }
            MultipartState::Preamble | MultipartState::Body | MultipartState::End => None,
        };
        if total_header_size.is_some_and(|size| size >= max_size) {
            return Err(PyRuntimeError::new_err(
                "Part exceeds maximum total header size.",
            ));
        }
        Ok(())
    }

    fn incomplete_header_prefix_size(&self, after_boundary: usize) -> Option<usize> {
        let suffix = &self.buffer[after_boundary..];
        (delimiter_suffix(&self.buffer, after_boundary) == DelimiterSuffix::Incomplete
            && !suffix.starts_with(b"-"))
        .then_some(suffix.len())
    }

    fn handle_body(&mut self, events: &mut Vec<MultipartEvent>) -> PyResult<bool> {
        let mut search_from = 0;
        while let Some(relative_index) = self.delimiter_finder.find(&self.buffer[search_from..]) {
            let index = search_from + relative_index;
            match delimiter_suffix(&self.buffer, index + self.delimiter_length) {
                DelimiterSuffix::Open(consumed) => {
                    self.current_total_header_size = consumed - (index + self.delimiter_length);
                    self.emit_data(events, index);
                    events.push(MultipartEvent::End);
                    self.buffer.drain(..consumed);
                    self.state = MultipartState::Header;
                    return Ok(true);
                }
                DelimiterSuffix::Close => {
                    self.emit_data(events, index);
                    events.push(MultipartEvent::End);
                    self.buffer.clear();
                    self.state = MultipartState::End;
                    return Ok(true);
                }
                DelimiterSuffix::Incomplete => {
                    self.check_incomplete_header_prefix(index + self.delimiter_length)?;
                    self.emit_data(events, index);
                    self.buffer.drain(..index);
                    return Ok(false);
                }
                DelimiterSuffix::Invalid => search_from = index + CRLF.len(),
                DelimiterSuffix::BareLineFeed => {
                    return Err(PyValueError::new_err("Invalid line break after delimiter"));
                }
            }
        }

        let retained = self.delimiter_length - 1;
        if self.buffer.len() > retained {
            let emitted = self.buffer.len() - retained;
            self.emit_data(events, emitted);
            self.buffer.drain(..emitted);
        }
        Ok(false)
    }

    fn emit_data(&self, events: &mut Vec<MultipartEvent>, length: usize) {
        if length > 0 {
            events.push(MultipartEvent::Data {
                data: self.buffer[..length].to_vec(),
            });
        }
    }
}

fn delimiter_suffix(buffer: &[u8], after_boundary: usize) -> DelimiterSuffix {
    let tail = &buffer[after_boundary..];
    if tail.is_empty() {
        return DelimiterSuffix::Incomplete;
    }
    if tail.starts_with(b"--") {
        return DelimiterSuffix::Close;
    }
    if tail[0] == b'-' {
        return if tail.len() == 1 {
            DelimiterSuffix::Incomplete
        } else {
            DelimiterSuffix::Invalid
        };
    }

    // RFC 2046 section 5.1.1 permits linear whitespace between the boundary and CRLF.
    let padding = tail
        .iter()
        .take_while(|byte| matches!(byte, b' ' | b'\t'))
        .count();
    let line_ending = &tail[padding..];
    if line_ending.is_empty() || line_ending == b"\r" {
        return DelimiterSuffix::Incomplete;
    }
    if line_ending.starts_with(CRLF) {
        return DelimiterSuffix::Open(after_boundary + padding + CRLF.len());
    }
    if line_ending[0] == b'\n' {
        return DelimiterSuffix::BareLineFeed;
    }
    DelimiterSuffix::Invalid
}
