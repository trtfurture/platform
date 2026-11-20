# SEO keyword and URL plan — Kenya

This is a first-pass keyword map, not search-volume evidence. Validate demand and seasonality in Google Keyword Planner, Google Trends and Search Console after launch. Do not create low-value pages simply to multiply keyword combinations.

| Search intent | Initial target phrases | Preferred landing page |
|---|---|---|
| General discovery | schools in Kenya; school directory Kenya; find schools in Kenya | `/schools` |
| Private schools | private schools in Kenya; private schools in Nairobi; private primary schools in Kiambu | `/directory/school` plus useful county/category landing pages |
| Public schools | public schools in Kenya; public primary schools in Nairobi; public secondary schools in Kenya | `/directory/school` with ownership filter |
| Boarding | boarding schools in Kenya; girls boarding schools Kenya; boys boarding schools Kenya | `/schools` with accommodation and school-level filters |
| Nursery/primary | nursery schools in Nairobi; primary schools in Kiambu; pre-primary schools near me | `/schools` with level and location filters |
| Secondary | secondary schools in Kenya; high schools in Nairobi; senior schools in Kiambu | `/schools` with level and location filters |
| Colleges / TVET | colleges in Kenya; TVET colleges in Nairobi; technical colleges near me | `/directory/college` |
| Universities | universities in Kenya; private universities in Kenya; public universities in Kenya | `/directory/university` |
| Commercial / institution owners | advertise my school in Kenya; list my school online; school advertising Kenya | `/advertise` |
| School web services | school website design Kenya; school portal Kenya; school management portal | `/school-portal` |
| Campus marketplace | student hostels in Nairobi; student accommodation near university; rentals near campus | `/campus-living` |

## Technical rules
- One descriptive, stable URL per school/institution.
- Unique title and meta description for each institution profile.
- Use canonical links for clean category landing pages; filtered query combinations are `noindex,follow` to avoid index bloat.
- County pages should be indexable only when they contain enough useful, unique institution information. The initial sitemap adds county landing pages only when at least three live institutions exist in that county.
- Publish original guides based on actual parent/student questions. Add review dates and source links where policies, fees or admissions change.
- Use useful image alt text; compress images and keep the site fast on mobile connections.
- Structured data is included for institutional profiles and the main WebSite/SearchAction entity. Validate the output with Google's Rich Results Test and Schema Markup Validator.
- Submit `/sitemap.xml` in Google Search Console and Bing Webmaster Tools after the domain is live.
- Never promise first position or immediate indexing. Measure impressions, clicks, indexed pages and enquiry actions over time.
