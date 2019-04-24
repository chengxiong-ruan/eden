// Copyright 2019 Facebook, Inc.
//
// This software may be used and distributed according to the terms of the
// GNU General Public License version 2 or any later version.

use std::{
    io::{Cursor, Seek, SeekFrom, Write},
    path::Path,
};

use byteorder::{BigEndian, ReadBytesExt, WriteBytesExt};
use bytes::Bytes;
use failure::{bail, ensure, format_err, Fallible};

use indexedlog::{
    log::IndexOutput,
    rotate::{LogRotate, OpenOptions},
};
use lz4_pyframe::{compress, decompress};
use types::{Key, Node};

use crate::{
    datastore::{DataStore, Delta, Metadata},
    error::KeyError,
    localstore::LocalStore,
    sliceext::SliceExt,
};

pub struct IndexedLogDataStore {
    log: LogRotate,
}

struct Entry {
    key: Key,
    metadata: Metadata,

    content: Option<Bytes>,
    compressed_content: Option<Bytes>,
}

impl Entry {
    pub fn new(key: Key, content: Bytes, metadata: Metadata) -> Self {
        Entry {
            key,
            content: Some(content),
            metadata,
            compressed_content: None,
        }
    }

    pub fn from_log(key: &Key, log: &LogRotate) -> Fallible<Self> {
        let mut log_entry = log.lookup(0, key.node.as_ref())?;
        let buf = log_entry
            .nth(0)
            .ok_or_else(|| KeyError::new(format_err!("Not found")))??;

        let mut cur = Cursor::new(buf);
        cur.seek(SeekFrom::Current(Node::len() as i64))?;

        let name_len = cur.read_u16::<BigEndian>()? as i64;
        cur.seek(SeekFrom::Current(name_len))?;

        let metadata = Metadata::read(&mut cur)?;

        let compressed_len = cur.read_u64::<BigEndian>()?;
        let compressed =
            buf.get_err(cur.position() as usize..(cur.position() + compressed_len) as usize)?;

        let key = key.clone();
        Ok(Entry {
            key,
            content: None,
            compressed_content: Some(compressed.into()),
            metadata,
        })
    }

    pub fn write_to_log(self, log: &mut LogRotate) -> Fallible<()> {
        let mut buf = Vec::new();
        buf.write_all(self.key.node.as_ref())?;
        let path_slice = self.key.path.as_byte_slice();
        buf.write_u16::<BigEndian>(path_slice.len() as u16)?;
        buf.write_all(path_slice)?;
        self.metadata.write(&mut buf)?;

        let compressed = if let Some(compressed) = self.compressed_content {
            compressed
        } else {
            if let Some(raw) = self.content {
                compress(&raw)?.into()
            } else {
                bail!("No content");
            }
        };

        buf.write_u64::<BigEndian>(compressed.len() as u64)?;
        buf.write_all(&compressed)?;

        Ok(log.append(buf)?)
    }

    pub fn content(&mut self) -> Fallible<Bytes> {
        if let Some(content) = self.content.as_ref() {
            return Ok(content.clone());
        }

        if let Some(compressed) = self.compressed_content.as_ref() {
            let raw = Bytes::from(decompress(&compressed)?);
            self.content = Some(raw.clone());
            Ok(raw)
        } else {
            bail!("No content");
        }
    }

    pub fn metadata(&self) -> &Metadata {
        &self.metadata
    }
}

impl IndexedLogDataStore {
    pub fn new(path: impl AsRef<Path>) -> Fallible<Self> {
        let log = OpenOptions::new()
            .max_log_count(10)
            .max_bytes_per_log(1 * 1024 * 1024 * 1024)
            .create(true)
            .index("node", |_| {
                vec![IndexOutput::Reference(0..Node::len() as u64)]
            })
            .open(path)?;
        Ok(IndexedLogDataStore { log })
    }

    pub fn add(&mut self, delta: &Delta, metadata: &Metadata) -> Fallible<()> {
        ensure!(delta.base.is_none(), "Deltas aren't supported.");

        let entry = Entry::new(delta.key.clone(), delta.data.clone(), metadata.clone());
        entry.write_to_log(&mut self.log)
    }

    pub fn flush(&mut self) -> Fallible<()> {
        self.log.flush()?;
        Ok(())
    }

    pub fn close(mut self) -> Fallible<()> {
        self.flush()
    }
}

impl LocalStore for IndexedLogDataStore {
    fn from_path(path: &Path) -> Fallible<Self> {
        IndexedLogDataStore::new(path)
    }

    fn get_missing(&self, keys: &[Key]) -> Fallible<Vec<Key>> {
        Ok(keys
            .iter()
            .filter(|k| Entry::from_log(k, &self.log).is_err())
            .map(|k| k.clone())
            .collect())
    }
}

impl DataStore for IndexedLogDataStore {
    fn get(&self, _key: &Key) -> Fallible<Vec<u8>> {
        unreachable!()
    }

    fn get_delta(&self, key: &Key) -> Fallible<Delta> {
        let mut entry = Entry::from_log(&key, &self.log)?;
        let content = entry.content()?;
        return Ok(Delta {
            data: content,
            base: None,
            key: key.clone(),
        });
    }

    fn get_delta_chain(&self, key: &Key) -> Fallible<Vec<Delta>> {
        let delta = self.get_delta(key)?;
        return Ok(vec![delta]);
    }

    fn get_meta(&self, key: &Key) -> Fallible<Metadata> {
        Ok(Entry::from_log(&key, &self.log)?.metadata().clone())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use bytes::Bytes;
    use tempfile::TempDir;

    use types::testutil::*;

    #[test]
    fn test_empty() {
        let tempdir = TempDir::new().unwrap();
        let log = IndexedLogDataStore::new(&tempdir).unwrap();
        log.close().unwrap();
    }

    #[test]
    fn test_add() {
        let tempdir = TempDir::new().unwrap();
        let mut log = IndexedLogDataStore::new(&tempdir).unwrap();

        let delta = Delta {
            data: Bytes::from(&[1, 2, 3, 4][..]),
            base: None,
            key: key("a", "1"),
        };
        let metadata = Default::default();

        log.add(&delta, &metadata).unwrap();
        log.close().unwrap();
    }

    #[test]
    fn test_add_get() {
        let tempdir = TempDir::new().unwrap();
        let mut log = IndexedLogDataStore::new(&tempdir).unwrap();

        let delta = Delta {
            data: Bytes::from(&[1, 2, 3, 4][..]),
            base: None,
            key: key("a", "1"),
        };
        let metadata = Default::default();

        log.add(&delta, &metadata).unwrap();
        log.close().unwrap();

        let log = IndexedLogDataStore::new(&tempdir).unwrap();
        let read_delta = log.get_delta(&delta.key).unwrap();
        assert_eq!(delta, read_delta);
    }

    #[test]
    fn test_lookup_failure() {
        let tempdir = TempDir::new().unwrap();
        let log = IndexedLogDataStore::new(&tempdir).unwrap();

        let key = key("a", "1");
        let err = log.get_delta(&key);

        if let Err(err) = err {
            assert!(err.downcast_ref::<KeyError>().is_some());
        } else {
            panic!("Lookup didn't fail");
        }
    }

    #[test]
    fn test_add_chain() -> Fallible<()> {
        let tempdir = TempDir::new()?;
        let mut log = IndexedLogDataStore::new(&tempdir)?;

        let delta = Delta {
            data: Bytes::from(&[1, 2, 3, 4][..]),
            base: Some(key("a", "1")),
            key: key("a", "2"),
        };
        let metadata = Default::default();

        assert!(log.add(&delta, &metadata).is_err());
        Ok(())
    }
}
