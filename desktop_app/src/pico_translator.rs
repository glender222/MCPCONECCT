pub struct TranslationResult {
    pub scopus: String,
    pub ieee: String,
    pub springer: String,
    pub ieee_wildcard_count: usize,
    pub ieee_valid: bool,
    pub scopus_warnings: Vec<String>,
}

pub fn count_wildcards(query: &str) -> usize {
    query.matches('*').count()
}

pub fn translate_pico_query(p: &str, i: &str, c: &str, o: &str) -> TranslationResult {
    let parse_block = |text: &str| -> Vec<String> {
        text.split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect()
    };

    let p_terms = parse_block(p);
    let i_terms = parse_block(i);
    let c_terms = parse_block(c);
    let o_terms = parse_block(o);

    // 1. Scopus: Wrap in TITLE-ABS-KEY ( ... ) and expand hyphenated wildcards
    let mut scopus_blocks = Vec::new();
    let mut scopus_warnings = Vec::new();

    let format_scopus_terms = |terms: &[String], warnings: &mut Vec<String>| -> String {
        let mut expanded = Vec::new();
        for t in terms {
            let term_clean = t.trim();
            if term_clean.contains("-") && term_clean.contains("*") {
                warnings.push(format!("Scopus no expande comodines tras guion: '{}'", term_clean));
                if term_clean.contains("pre-train*") {
                    expanded.push("\"pre-trained\" OR \"pre-training\"".to_string());
                } else if term_clean.contains("fine-tun*") {
                    expanded.push("\"fine-tuning\" OR \"fine-tuned\"".to_string());
                } else {
                    expanded.push(term_clean.to_string());
                }
            } else {
                expanded.push(term_clean.to_string());
            }
        }
        format!("TITLE-ABS-KEY ( {} )", expanded.join(" OR "))
    };

    if !p_terms.is_empty() { scopus_blocks.push(format_scopus_terms(&p_terms, &mut scopus_warnings)); }
    if !i_terms.is_empty() { scopus_blocks.push(format_scopus_terms(&i_terms, &mut scopus_warnings)); }
    if !c_terms.is_empty() { scopus_blocks.push(format_scopus_terms(&c_terms, &mut scopus_warnings)); }
    if !o_terms.is_empty() { scopus_blocks.push(format_scopus_terms(&o_terms, &mut scopus_warnings)); }

    let scopus_query = scopus_blocks.join(" AND ");

    // 2. IEEE: (("All Metadata":"...") OR ...) with strict 10 wildcard check
    let mut ieee_blocks = Vec::new();
    let mut ieee_total_wildcards = 0;

    let format_ieee_terms = |terms: &[String], wildcard_count: &mut usize| -> String {
        let mut parts = Vec::new();
        for t in terms {
            let clean = t.trim().trim_matches('"').trim_matches('\'');
            if clean.contains('*') {
                *wildcard_count += clean.matches('*').count();
            }
            parts.push(format!("(\"All Metadata\":\"{}\")", clean));
        }
        format!("({})", parts.join(" OR "))
    };

    if !p_terms.is_empty() { ieee_blocks.push(format_ieee_terms(&p_terms, &mut ieee_total_wildcards)); }
    if !i_terms.is_empty() { ieee_blocks.push(format_ieee_terms(&i_terms, &mut ieee_total_wildcards)); }
    if !c_terms.is_empty() { ieee_blocks.push(format_ieee_terms(&c_terms, &mut ieee_total_wildcards)); }
    if !o_terms.is_empty() { ieee_blocks.push(format_ieee_terms(&o_terms, &mut ieee_total_wildcards)); }

    let ieee_query = ieee_blocks.join(" AND ");
    let ieee_valid = ieee_total_wildcards <= 10;

    // 3. Springer: Simple clauses without unsupported wildcards
    let mut springer_blocks = Vec::new();
    let format_springer_terms = |terms: &[String]| -> String {
        let clean_terms: Vec<String> = terms.iter().map(|t| {
            let clean = t.trim().replace('*', "");
            if clean.starts_with('"') { clean } else { format!("\"{}\"", clean) }
        }).collect();
        format!("({})", clean_terms.join(" OR "))
    };

    if !p_terms.is_empty() { springer_blocks.push(format_springer_terms(&p_terms)); }
    if !i_terms.is_empty() { springer_blocks.push(format_springer_terms(&i_terms)); }
    if !c_terms.is_empty() { springer_blocks.push(format_springer_terms(&c_terms)); }
    if !o_terms.is_empty() { springer_blocks.push(format_springer_terms(&o_terms)); }

    let springer_query = springer_blocks.join(" AND ");

    TranslationResult {
        scopus: scopus_query,
        ieee: ieee_query,
        springer: springer_query,
        ieee_wildcard_count: ieee_total_wildcards,
        ieee_valid,
        scopus_warnings,
    }
}
