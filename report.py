def print_report(results):

    print("\n")
    print("FUNERAL HOME CONVERSION OPPORTUNITY AUDIT")
    print("="*78)


    for r in results:

        print("\n")
        print(r["domain"])

        print(
            f"Pages Indexed:      {r['pages']}"
        )

        print(
            f"Conversion Score:   {r['conversion']}/15"
        )

        print(
            f"Opportunity Score:  {r['opportunity']}/15"
        )

        print(
            f"Lead Value Score:   {r.get('lead_value',0)}/30"
        )

        print(
            f"Priority:           {r['priority']}"
        )

        print(
            "Missing:            "
            +
            ", ".join(r["missing"])
        )

        print("Recommended Pitch:")

        for p in r["pitch"]:
            print(
                "🔥 " + p
            )
