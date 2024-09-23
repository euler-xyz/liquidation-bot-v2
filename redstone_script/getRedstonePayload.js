import { DataPackagesWrapper, DataServiceWrapper } from "@redstone-finance/evm-connector";
import { RedstonePayload } from "@redstone-finance/protocol";
import { parseAbi, hexToString, encodeFunctionData, encodePacked } from "viem";

const dataServiceId = "redstone-primary-prod";
const redstoneCoreOracleAbi = parseAbi([
    "function updatePrice(uint48 timestamp)",
]);

const getRedstonePayload = async (feedIds) => {
    const feedIdStrings = feedIds.map((feedId) => {
        return hexToString(feedId, { size: 32 });
    });

    const dataServiceWrapper = new DataServiceWrapper({
        dataServiceId,
        dataPackagesIds: feedIdStrings,
        uniqueSignersCount: 3,
      });

    const allDataPackages = await dataServiceWrapper.getDataPackagesForPayload();

    // console.log(allDataPackages)

    return feedIdStrings.map((feedIdString) => {
        const adapterDataPackages = allDataPackages.filter(
            ({ dataPackage }) => dataPackage.dataPackageId === feedIdString
        );

        const timestamps = adapterDataPackages.map(
            ({ dataPackage }) => dataPackage.timestampMilliseconds
        );

        const payloadTimestamp = timestamps[0] / 1000;

        const redstonePayload = RedstonePayload.prepare(
            adapterDataPackages,
            dataServiceWrapper.getUnsignedMetadata()
        );

        const updatePriceCalldata = encodeFunctionData({
            abi: redstoneCoreOracleAbi,
            functionName: "updatePrice",
            args: [payloadTimestamp],
        });

        const data = encodePacked(
            ["bytes", "bytes"],
            [updatePriceCalldata, redstonePayload]
        );

        return {
            description: `Update RedStone Core price for ${feedIdString}`,
            data,
          };
    });    
};
const feedIds = JSON.parse(process.argv[2]);
const results = await getRedstonePayload(feedIds);
console.log(JSON.stringify(results, null, 2));