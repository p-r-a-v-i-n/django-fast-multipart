#![no_main]

use libfuzzer_sys::fuzz_target;
use pyo3::Python;
use std::sync::Once;

// Compile the production parser directly so the fuzz executable does not also
// build the Python extension's cdylib with sanitizer instrumentation.
#[allow(dead_code)]
#[path = "../../rust/src/multipart.rs"]
mod multipart;

use multipart::{MultipartEvent, MultipartParser};

const BOUNDARY: &[u8] = b"fuzz-boundary";

#[derive(Debug, PartialEq)]
enum Event {
    Begin(Vec<(Vec<u8>, Vec<u8>)>),
    Data(Vec<u8>),
    End,
    Raw,
}

#[derive(Debug, PartialEq)]
enum Terminal {
    FeedError(ParserError),
    EofError(ParserError),
    Finished(Result<(), ParserError>),
}

#[derive(Debug, PartialEq)]
enum ParserError {
    HeaderLimit,
    Other(String),
}

#[derive(Debug, PartialEq)]
struct Outcome {
    events: Vec<Event>,
    terminal: Terminal,
}

fn normalize_error(error: impl ToString) -> ParserError {
    let message = error.to_string();
    // The Django adapter exposes each internal header-limit failure as the
    // same MultiPartParserError, regardless of which threshold is seen first.
    let is_header_limit = [
        "Header line exceeds maximum size.",
        "Part exceeds maximum header count.",
        "Part exceeds maximum total header size.",
    ]
    .iter()
    .any(|candidate| message.ends_with(candidate));
    if is_header_limit {
        ParserError::HeaderLimit
    } else {
        ParserError::Other(message)
    }
}

fn append_events(output: &mut Vec<Event>, events: Vec<MultipartEvent<Vec<u8>>>) {
    for event in events {
        match event {
            MultipartEvent::Begin { headers } => output.push(Event::Begin(headers)),
            MultipartEvent::Data { data } => {
                if let Some(Event::Data(previous)) = output.last_mut() {
                    previous.extend(data);
                } else {
                    output.push(Event::Data(data));
                }
            }
            MultipartEvent::End => output.push(Event::End),
            MultipartEvent::Raw => output.push(Event::Raw),
        }
    }
}

fn parse(request: &[u8], chunk_size: usize, control: u8) -> Outcome {
    let max_size = (control & 0x20 != 0).then_some(4_096);
    let max_header_count = if control & 0x40 == 0 { 255 } else { 2 };
    let max_header_size = if control & 0x80 == 0 { 1_024 } else { 64 };
    let mut parser = MultipartParser::new(
        BOUNDARY.to_vec(),
        max_size,
        max_header_count,
        max_header_size,
        Some(1_024),
    )
    .expect("the fixed fuzz boundary is valid");
    let mut events = Vec::new();

    for chunk in request.chunks(chunk_size) {
        match parser.feed_map_data(chunk, <[u8]>::to_vec) {
            Ok(produced) => append_events(&mut events, produced),
            Err(error) => {
                return Outcome {
                    events,
                    terminal: Terminal::FeedError(normalize_error(error)),
                };
            }
        }
    }

    match parser.feed_eof_map_data(<[u8]>::to_vec) {
        Ok(produced) => append_events(&mut events, produced),
        Err(error) => {
            return Outcome {
                events,
                terminal: Terminal::EofError(normalize_error(error)),
            };
        }
    }

    Outcome {
        events,
        terminal: Terminal::Finished(parser.finish().map_err(normalize_error)),
    }
}

fuzz_target!(|input: &[u8]| {
    let Some((&control, request)) = input.split_first() else {
        return;
    };
    let chunk_size = usize::from(control & 0x1f) + 1;

    static INITIALIZE_PYTHON: Once = Once::new();
    INITIALIZE_PYTHON.call_once(Python::initialize);
    Python::attach(|_| {
        let contiguous = parse(request, request.len().max(1), control);
        let incremental = parse(request, chunk_size, control);
        match (&contiguous.terminal, &incremental.terminal) {
            // Events returned by earlier incremental feed calls remain visible
            // when a later call exceeds a limit. A one-shot call returns only
            // the error, so compare the common terminal result in this case.
            (Terminal::FeedError(left), Terminal::FeedError(right)) => {
                assert_eq!(left, right);
            }
            _ => assert_eq!(contiguous, incremental),
        }
    });
});
