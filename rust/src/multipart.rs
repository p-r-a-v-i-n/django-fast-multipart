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
const MAX_BOUNDARY_LENGTH: usize = 201;

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum MultipartState {
    Preamble,
    Header,
    Body,
    Discard,
    End,
}

#[derive(Debug, Clone)]
pub enum MultipartEvent<D> {
    Begin { headers: Vec<(Vec<u8>, Vec<u8>)> },
    Data { data: D },
    End,
    Raw,
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
    size: usize,
    current_headers: Vec<(Vec<u8>, Vec<u8>)>,
    current_total_header_size: usize,
    pending_headers: bool,
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
        // Django performs character validation before constructing this
        // parser and accepts boundary values through 201 bytes.
        if boundary.is_empty() || boundary.len() > MAX_BOUNDARY_LENGTH {
            return Err(PyValueError::new_err(format!(
                "Boundary length must be between 1 and {MAX_BOUNDARY_LENGTH} bytes."
            )));
        }

        let dash_boundary = [b"--".as_slice(), &boundary].concat();
        let dash_boundary_finder = Box::new(memmem::Finder::new(&dash_boundary).into_owned());
        Ok(Self {
            max_size,
            max_header_count,
            max_header_size,
            max_total_header_size,
            state: MultipartState::Preamble,
            buffer: Vec::new(),
            dash_boundary,
            delimiter_length: CRLF.len() + boundary.len() + 2,
            dash_boundary_finder,
            size: 0,
            current_headers: Vec::new(),
            current_total_header_size: 0,
            pending_headers: false,
            eof_received: false,
        })
    }

    pub fn state(&self) -> MultipartState {
        self.state
    }

    // Map body slices before they are drained from the parser buffer. The
    // Python binding can therefore create its final `bytes` value without an
    // intermediate `Vec<u8>` allocation and copy.
    pub fn feed_map_data<D, F>(
        &mut self,
        data: &[u8],
        mut map_data: F,
    ) -> PyResult<Vec<MultipartEvent<D>>>
    where
        F: FnMut(&[u8]) -> D,
    {
        let mut events = Vec::new();
        if self.eof_received {
            return Err(PyValueError::new_err("Cannot feed data after EOF."));
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
                MultipartState::Body => self.handle_body(&mut events, &mut map_data)?,
                MultipartState::Discard | MultipartState::End => {
                    self.handle_raw_segment(&mut events)?
                }
            };
            if !progressed {
                return Ok(events);
            }
        }
    }

    pub fn feed_eof_map_data<D, F>(&mut self, mut map_data: F) -> PyResult<Vec<MultipartEvent<D>>>
    where
        F: FnMut(&[u8]) -> D,
    {
        if self.eof_received {
            return Ok(Vec::new());
        }
        self.eof_received = true;
        let mut events = Vec::new();

        if self.pending_headers {
            events.push(MultipartEvent::Begin {
                headers: std::mem::take(&mut self.current_headers),
            });
            self.current_total_header_size = 0;
            self.pending_headers = false;
        }

        self.check_eof_header_size()?;
        self.current_headers.clear();

        if self.state == MultipartState::Body {
            if let Some(index) = self.dash_boundary_finder.find(&self.buffer) {
                let after_boundary = index + self.dash_boundary.len();
                if delimiter_suffix(&self.buffer, after_boundary) == DelimiterSuffix::Incomplete {
                    self.emit_data(
                        &mut events,
                        body_data_end(&self.buffer, index),
                        &mut map_data,
                    );
                    events.push(MultipartEvent::End);
                    // Django creates a following RAW segment only when bytes
                    // remain after the boundary token. Preserve that
                    // distinction for the adapter's field-count accounting.
                    self.state = if after_boundary == self.buffer.len() {
                        MultipartState::End
                    } else {
                        MultipartState::Discard
                    };
                    self.buffer.clear();
                    return Ok(events);
                }
            }
        }

        let data = std::mem::take(&mut self.buffer);
        if self.state == MultipartState::Body && !data.is_empty() {
            events.push(MultipartEvent::Data {
                data: map_data(&data),
            });
        }
        Ok(events)
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
        // Django treats the raw boundary token as a separator even when it
        // isn't at the beginning of a line.
        if let Some(index) = self.dash_boundary_finder.find(&self.buffer) {
            let after_boundary = index + self.dash_boundary.len();
            match delimiter_suffix(&self.buffer, after_boundary) {
                DelimiterSuffix::Open(consumed) => {
                    self.current_total_header_size = consumed - after_boundary;
                    self.buffer.drain(..consumed);
                    self.state = MultipartState::Header;
                    return Ok(true);
                }
                DelimiterSuffix::Close => {
                    self.buffer.drain(..after_boundary);
                    self.state = MultipartState::End;
                    return Ok(true);
                }
                DelimiterSuffix::Incomplete => {
                    self.check_incomplete_header_prefix(after_boundary)?;
                    self.buffer.drain(..index);
                    return Ok(false);
                }
                DelimiterSuffix::Invalid | DelimiterSuffix::BareLineFeed => {
                    self.buffer.drain(..after_boundary);
                    self.state = MultipartState::Discard;
                    return Ok(true);
                }
            }
        }

        let retained = self.dash_boundary.len() + 1;
        if self.buffer.len() > retained {
            self.buffer.drain(..self.buffer.len() - retained);
        }
        Ok(false)
    }

    fn handle_header<D>(&mut self, events: &mut Vec<MultipartEvent<D>>) -> PyResult<bool> {
        let next_boundary = self.dash_boundary_finder.find(&self.buffer);
        let line_end = memmem::find(&self.buffer, CRLF);
        if let Some(index) = next_boundary
            .filter(|boundary| line_end.is_none_or(|line_terminator| *boundary < line_terminator))
        {
            if index > self.max_header_size {
                return Err(PyRuntimeError::new_err("Header line exceeds maximum size."));
            }
            self.check_total_header_size(index)?;
            self.current_headers.clear();
            self.current_total_header_size = 0;
            return self.handle_raw_boundary(events, index);
        }

        if let Some(index) = memmem::find(&self.buffer, CRLF) {
            if index == 0 {
                self.check_total_header_size(CRLF.len())?;
                self.buffer.drain(..CRLF.len());
                self.pending_headers = true;
                self.state = MultipartState::Body;
                return Ok(true);
            }
            if index > self.max_header_size {
                return Err(PyRuntimeError::new_err("Header line exceeds maximum size."));
            }
            self.check_total_header_size(index + CRLF.len())?;
            let line = &self.buffer[..index];
            // Match Django's header classification: ignore lines without a
            // colon and remove trailing spaces, but preserve other bytes in
            // the header name for the adapter to decode and classify.
            if let Some(separator) = memchr::memchr(b':', line) {
                if self.current_headers.len() == self.max_header_count {
                    return Err(PyRuntimeError::new_err(
                        "Part exceeds maximum header count.",
                    ));
                }
                let raw_name = &line[..separator];
                let name_length = raw_name
                    .iter()
                    .rposition(|byte| *byte != b' ')
                    .map_or(0, |index| index + 1);
                let name = &raw_name[..name_length];
                let value = line[separator + 1..].trim_ascii();
                self.current_headers.push((name.to_vec(), value.to_vec()));
            }
            self.current_total_header_size = self
                .current_total_header_size
                .saturating_add(index + CRLF.len());
            self.buffer.drain(..index + CRLF.len());
            return Ok(true);
        }
        // Do not charge an ambiguous trailing CR or partial boundary token to
        // the header until the next chunk disambiguates it.
        let retained = if self.buffer.ends_with(b"\r") {
            1
        } else {
            partial_suffix_length(&self.buffer, &self.dash_boundary)
        };
        let pending = self.buffer.len() - retained;
        if pending > self.max_header_size {
            return Err(PyRuntimeError::new_err("Header line exceeds maximum size."));
        }
        self.check_total_header_size(pending)?;
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
            MultipartState::Preamble
            | MultipartState::Body
            | MultipartState::Discard
            | MultipartState::End => None,
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

    fn handle_body<D, F>(
        &mut self,
        events: &mut Vec<MultipartEvent<D>>,
        map_data: &mut F,
    ) -> PyResult<bool>
    where
        F: FnMut(&[u8]) -> D,
    {
        if self.pending_headers {
            if self.buffer.len() < self.dash_boundary.len()
                && self.dash_boundary.starts_with(&self.buffer)
            {
                return Ok(false);
            }
            if self.buffer.starts_with(&self.dash_boundary) {
                self.current_headers.clear();
                self.current_total_header_size = 0;
                self.pending_headers = false;
                self.state = MultipartState::Discard;
                return self.handle_raw_boundary(events, 0);
            }
            events.push(MultipartEvent::Begin {
                headers: std::mem::take(&mut self.current_headers),
            });
            self.current_total_header_size = 0;
            self.pending_headers = false;
        }

        if let Some(index) = self.dash_boundary_finder.find(&self.buffer) {
            let after_boundary = index + self.dash_boundary.len();
            let data_end = body_data_end(&self.buffer, index);
            match delimiter_suffix(&self.buffer, after_boundary) {
                DelimiterSuffix::Open(consumed) => {
                    self.current_total_header_size = consumed - after_boundary;
                    self.emit_data(events, data_end, map_data);
                    events.push(MultipartEvent::End);
                    self.buffer.drain(..consumed);
                    self.state = MultipartState::Header;
                    return Ok(true);
                }
                DelimiterSuffix::Close => {
                    self.emit_data(events, data_end, map_data);
                    events.push(MultipartEvent::End);
                    self.buffer.drain(..after_boundary);
                    self.state = MultipartState::End;
                    return Ok(true);
                }
                DelimiterSuffix::Incomplete => {
                    self.check_incomplete_header_prefix(after_boundary)?;
                    self.emit_data(events, data_end, map_data);
                    self.buffer.drain(..data_end);
                    return Ok(false);
                }
                DelimiterSuffix::Invalid | DelimiterSuffix::BareLineFeed => {
                    // Django's BoundaryIter treats the raw boundary token as a
                    // separator without validating its suffix. Finish the
                    // current part and ignore the resulting RAW segment until
                    // another usable boundary is found.
                    self.emit_data(events, data_end, map_data);
                    events.push(MultipartEvent::End);
                    self.buffer.drain(..after_boundary);
                    self.state = MultipartState::Discard;
                    return Ok(true);
                }
            }
        }

        let retained = self.delimiter_length - 1;
        if self.buffer.len() > retained {
            let emitted = self.buffer.len() - retained;
            self.emit_data(events, emitted, map_data);
            self.buffer.drain(..emitted);
        }
        Ok(false)
    }

    fn handle_raw_segment<D>(&mut self, events: &mut Vec<MultipartEvent<D>>) -> PyResult<bool> {
        // Django continues classifying every segment after a boundary token,
        // including epilogues and data after a closing-boundary marker.
        let next_boundary = self.dash_boundary_finder.find(&self.buffer);
        let header_end = memmem::find(&self.buffer, b"\r\n\r\n");

        if header_end.is_some_and(|index| next_boundary.is_none_or(|boundary| index < boundary)) {
            self.current_headers.clear();
            self.current_total_header_size = 0;
            self.state = MultipartState::Header;
            return Ok(true);
        }

        if let Some(index) = next_boundary {
            return self.handle_raw_boundary(events, index);
        }

        self.check_total_header_size(self.buffer.len())?;
        Ok(false)
    }

    fn handle_raw_boundary<D>(
        &mut self,
        events: &mut Vec<MultipartEvent<D>>,
        index: usize,
    ) -> PyResult<bool> {
        let after_boundary = index + self.dash_boundary.len();
        match delimiter_suffix(&self.buffer, after_boundary) {
            DelimiterSuffix::Open(consumed) => {
                events.push(MultipartEvent::Raw);
                self.current_total_header_size = consumed - after_boundary;
                self.buffer.drain(..consumed);
                self.state = MultipartState::Header;
                Ok(true)
            }
            DelimiterSuffix::Close => {
                events.push(MultipartEvent::Raw);
                self.buffer.drain(..after_boundary);
                self.state = MultipartState::End;
                Ok(true)
            }
            DelimiterSuffix::Incomplete => {
                self.buffer.drain(..index);
                Ok(false)
            }
            DelimiterSuffix::Invalid | DelimiterSuffix::BareLineFeed => {
                events.push(MultipartEvent::Raw);
                self.buffer.drain(..after_boundary);
                self.state = MultipartState::Discard;
                Ok(true)
            }
        }
    }

    fn emit_data<D, F>(&self, events: &mut Vec<MultipartEvent<D>>, length: usize, map_data: &mut F)
    where
        F: FnMut(&[u8]) -> D,
    {
        if length > 0 {
            events.push(MultipartEvent::Data {
                data: map_data(&self.buffer[..length]),
            });
        }
    }
}

fn body_data_end(buffer: &[u8], boundary_start: usize) -> usize {
    let mut end = boundary_start;
    if end > 0 && buffer[end - 1] == b'\n' {
        end -= 1;
    }
    if end > 0 && buffer[end - 1] == b'\r' {
        end -= 1;
    }
    end
}

fn partial_suffix_length(buffer: &[u8], token: &[u8]) -> usize {
    let maximum = buffer.len().min(token.len().saturating_sub(1));
    (1..=maximum)
        .rev()
        .find(|length| token.starts_with(&buffer[buffer.len() - length..]))
        .unwrap_or(0)
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
