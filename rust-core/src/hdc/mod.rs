//! Hyperdimensional Computing — brain-inspired fixed-width vectors.
//! Pure Rust, zero dependencies beyond std + rand.

use rand::Rng;
use serde::{Deserialize, Serialize};

pub const DEFAULT_DIM: usize = 10000;

pub type HyperVector = Vec<i8>;

pub fn random_hv(dim: usize) -> HyperVector {
    let mut rng = rand::rng();
    (0..dim).map(|_| if rng.random_bool(0.5) { 1i8 } else { -1i8 }).collect()
}

#[allow(dead_code)]
pub fn bind(a: &HyperVector, b: &HyperVector) -> HyperVector {
    a.iter().zip(b.iter()).map(|(x, y)| x * y).collect()
}

#[allow(dead_code)]
pub fn bundle(vecs: &[&HyperVector]) -> HyperVector {
    if vecs.is_empty() {
        return vec![];
    }
    let dim = vecs[0].len();
    (0..dim)
        .map(|i| {
            let sum: i32 = vecs.iter().map(|v| v[i] as i32).sum();
            if sum > 0 { 1i8 } else if sum < 0 { -1i8 } else { 1i8 }
        })
        .collect()
}

pub fn similarity(a: &HyperVector, b: &HyperVector) -> f64 {
    if a.is_empty() {
        return 0.0;
    }
    let dot: i64 = a.iter().zip(b.iter()).map(|(x, y)| (*x as i64) * (*y as i64)).sum();
    dot as f64 / a.len() as f64
}

#[allow(dead_code)]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Habit {
    pub description: String,
    pub status: String,
    pub confidence: f64,
    pub created_at: f64,
    pub verified_at: Option<f64>,
}

#[allow(dead_code)]
#[derive(Serialize, Deserialize)]
pub struct HabitEntry {
    pub habit: Habit,
    pub vector: HyperVector,
}

#[derive(Default, Serialize, Deserialize)]
pub struct Codebook {
    pub dim: usize,
    pub vectors: std::collections::HashMap<String, HyperVector>,
}

impl Codebook {
    pub fn new(dim: usize) -> Self {
        Self { dim, vectors: Default::default() }
    }

    pub fn get(&mut self, concept: &str) -> &HyperVector {
        let dim = self.dim;
        self.vectors.entry(concept.to_string()).or_insert_with(|| random_hv(dim))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_orthogonal() {
        let a = random_hv(10000);
        let b = random_hv(10000);
        assert!(similarity(&a, &b).abs() < 0.05);
    }

    #[test]
    fn test_bind_self_inverse() {
        let a = random_hv(10000);
        let b = random_hv(10000);
        let bound = bind(&a, &b);
        let recovered = bind(&bound, &b);
        assert!(similarity(&recovered, &a) > 0.95);
    }

    #[test]
    fn test_bundle_preserves() {
        let a = random_hv(10000);
        let b = random_hv(10000);
        let c = random_hv(10000);
        let bundled = bundle(&[&a, &b, &c]);
        assert!(similarity(&bundled, &a) > 0.2);
        assert!(similarity(&bundled, &b) > 0.2);
        let d = random_hv(10000);
        assert!(similarity(&bundled, &d).abs() < 0.1);
    }
}
